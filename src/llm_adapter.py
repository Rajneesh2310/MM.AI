"""Minimal local-only LLM adapter for MM.AI.

Responsibility:
- Accept an ``LLMPromptPayload`` produced by ``build_llm_prompt``.
- POST its ``prompt_text`` to a *local* runtime (Ollama ``/api/generate`` or
  any OpenAI-compatible ``/v1/chat/completions`` endpoint).
- Return the model's plain-text reply verbatim wrapped in an ``LLMResponse``.

Out of scope (intentionally absent):
- Cloud API calls / SDKs.
- Tool-calling, function-calling, autonomous agent loops, self-prompting.
- Memory, conversation history, retries.
- Post-processing, summarisation, interpretation, sentiment scoring.
- Streaming (always ``stream=false``).

Security posture:
- The endpoint URL is parsed and rejected if the resolved host is not a
  loopback or RFC1918 private address. Public hosts cannot be reached
  through this adapter even if the env var is misconfigured.
- The model receives only the prompt text. No parquet paths, dataframes,
  filesystem context, or MM internals are passed.
- Every failure mode (timeout, connection refused, malformed JSON, missing
  response field, unsupported backend) is surfaced as a deterministic
  ``LLMResponse(ok=False, error=...)``. The function never raises.
"""

from __future__ import annotations

import json
import socket
import time
import urllib.error
import urllib.request
from datetime import datetime
from ipaddress import ip_address
from typing import Any, Callable
from urllib.parse import urlparse

from .llm_config import LLMConfig, SUPPORTED_BACKENDS, load_config_from_env
from .llm_models import LLMPromptPayload, TIMESTAMP_FORMAT
from .llm_response_models import LLMResponse

# A transport is a callable that POSTs JSON to ``url`` and returns the parsed
# response as a dict. The default transport uses ``urllib``; tests inject a
# fake transport so they never touch the network.
Transport = Callable[[str, dict, float], Any]

_LOCAL_HOSTS: frozenset[str] = frozenset({"localhost", "127.0.0.1", "0.0.0.0", "::1"})
_ALLOWED_SCHEMES: frozenset[str] = frozenset({"http", "https"})
_OPENROUTER_HOSTS: frozenset[str] = frozenset({"openrouter.ai", "www.openrouter.ai"})

# Canonical Ollama generate path. The /api/generate handler accepts the
# {"model", "prompt", "stream"} body shape we emit. Anything else (root,
# /v1/chat/completions, /api/chat) responds 404 to our body. We coerce
# the path here so a slightly-misconfigured MM_AI_LLM_ENDPOINT does not
# turn into a confusing "404 Not Found" at runtime.
_OLLAMA_GENERATE_PATH = "/api/generate"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _now_timestamp() -> str:
    return datetime.now().strftime(TIMESTAMP_FORMAT)


def normalise_ollama_endpoint(url: str) -> str:
    """Force the endpoint path to ``/api/generate`` for Ollama.

    Accepted user inputs and how they normalise:

    * ``http://localhost:11434``                  -> append ``/api/generate``
    * ``http://localhost:11434/``                 -> append ``/api/generate``
    * ``http://localhost:11434/v1/chat/completions`` -> rewrite to
      ``/api/generate`` (OpenAI-compat path is not what our body targets)
    * ``http://localhost:11434/api/chat``         -> rewrite to ``/api/generate``
    * ``http://localhost:11434/api/generate``     -> unchanged

    The query string and fragment are stripped — the Ollama generate
    endpoint does not consume them and they only obscure debugging.
    """
    if not url or not isinstance(url, str):
        return url
    try:
        parsed = urlparse(url)
    except (ValueError, TypeError):
        return url
    if parsed.scheme not in _ALLOWED_SCHEMES or not parsed.netloc:
        return url
    current_path = (parsed.path or "").rstrip("/")
    if current_path == _OLLAMA_GENERATE_PATH:
        # Already canonical; drop only query/fragment.
        return f"{parsed.scheme}://{parsed.netloc}{_OLLAMA_GENERATE_PATH}"
    return f"{parsed.scheme}://{parsed.netloc}{_OLLAMA_GENERATE_PATH}"


def _is_local_endpoint(url: str) -> tuple[bool, str]:
    """Return ``(True, "")`` iff the URL is loopback or RFC1918 private."""
    if not url or not isinstance(url, str):
        return False, "endpoint_missing"
    try:
        parsed = urlparse(url)
    except (ValueError, TypeError) as exc:
        return False, f"invalid_url: {exc}"
    if not parsed.scheme:
        return False, "endpoint_missing_scheme"
    if parsed.scheme not in _ALLOWED_SCHEMES:
        return False, f"unsupported_scheme: {parsed.scheme}"
    host = (parsed.hostname or "").lower()
    if not host:
        return False, "endpoint_missing_host"
    if host in _LOCAL_HOSTS:
        return True, ""
    # Numeric IP literal?
    try:
        ip = ip_address(host)
    except ValueError:
        try:
            resolved = socket.gethostbyname(host)
        except OSError as exc:
            return False, f"resolve_failure: {exc}"
        try:
            ip = ip_address(resolved)
        except ValueError:
            return False, f"non_ip_resolution: {resolved}"
    if ip.is_loopback or ip.is_private:
        return True, ""
    return False, f"non_local_endpoint: {host}"


def _http_post(url: str, body: dict, timeout: float) -> Any:
    """Default transport: POST JSON with urllib, parse JSON response."""
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "MM.AI-LLM-Adapter/1.0",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310
        raw = resp.read()
    text = raw.decode("utf-8", errors="replace")
    return json.loads(text)


def _http_post_with_headers(
    url: str, body: dict, timeout: float, headers: dict[str, str]
) -> Any:
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "MM.AI-LLM-Adapter/1.0",
            **headers,
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310
        raw = resp.read()
    text = raw.decode("utf-8", errors="replace")
    return json.loads(text)


# ---------------------------------------------------------------------------
# Backend dispatch
# ---------------------------------------------------------------------------


def _call_ollama(
    prompt_text: str, config: LLMConfig, transport: Transport
) -> str:
    body = {
        "model": config.model_name,
        "prompt": prompt_text,
        "stream": False,
    }
    endpoint = normalise_ollama_endpoint(config.endpoint_url)
    raw = transport(endpoint, body, config.timeout_seconds)
    if not isinstance(raw, dict):
        raise ValueError(f"unexpected_response_type: {type(raw).__name__}")
    if "response" not in raw:
        raise ValueError("missing_response_field")
    text = raw.get("response", "")
    if not isinstance(text, str):
        raise ValueError("response_field_not_a_string")
    return text


def _call_openai_compat(
    prompt_text: str, config: LLMConfig, transport: Transport
) -> str:
    body = {
        "model": config.model_name,
        "messages": [{"role": "user", "content": prompt_text}],
        "stream": False,
    }
    raw = transport(config.endpoint_url, body, config.timeout_seconds)
    if not isinstance(raw, dict):
        raise ValueError(f"unexpected_response_type: {type(raw).__name__}")
    choices = raw.get("choices")
    if not isinstance(choices, list) or not choices:
        raise ValueError("missing_choices")
    first = choices[0]
    if not isinstance(first, dict):
        raise ValueError("choice_not_a_dict")
    msg = first.get("message")
    if not isinstance(msg, dict):
        raise ValueError("missing_message")
    content = msg.get("content")
    if not isinstance(content, str):
        raise ValueError("missing_content")
    return content


def _call_openrouter(prompt_text: str, config: LLMConfig) -> str:
    if not config.api_key:
        raise ValueError("missing_openrouter_api_key")
    body = {
        "model": config.model_name,
        "messages": [{"role": "user", "content": prompt_text}],
        "stream": False,
    }
    raw = _http_post_with_headers(
        config.endpoint_url,
        body,
        config.timeout_seconds,
        {"Authorization": f"Bearer {config.api_key}"},
    )
    if not isinstance(raw, dict):
        raise ValueError(f"unexpected_response_type: {type(raw).__name__}")
    choices = raw.get("choices")
    if not isinstance(choices, list) or not choices:
        raise ValueError("missing_choices")
    first = choices[0]
    if not isinstance(first, dict):
        raise ValueError("choice_not_a_dict")
    msg = first.get("message")
    if not isinstance(msg, dict):
        raise ValueError("missing_message")
    content = msg.get("content")
    if not isinstance(content, str):
        raise ValueError("missing_content")
    return content


def _is_openrouter_endpoint(url: str) -> tuple[bool, str]:
    try:
        parsed = urlparse(url)
    except (ValueError, TypeError) as exc:
        return False, f"invalid_url: {exc}"
    if parsed.scheme != "https":
        return False, "openrouter_requires_https"
    host = (parsed.hostname or "").lower()
    if host not in _OPENROUTER_HOSTS:
        return False, f"openrouter_host_not_allowed: {host or 'missing'}"
    if (parsed.path or "").rstrip("/") != "/api/v1/chat/completions":
        return False, "openrouter_path_not_allowed"
    return True, ""


def _read_http_error_body(exc: urllib.error.HTTPError) -> str:
    """Return ``" — <inner>"`` extracted from an Ollama JSON error body.

    Ollama responds with ``{"error": "model 'X' not found, try pulling it
    first"}`` on a 404 for an unknown model. Surfacing that detail behind
    the existing ``http_error: <code> <reason>`` prefix preserves the
    internal contract used by tests while giving operators an actionable
    hint. Returns an empty string when no usable body is available.
    """
    try:
        reader = getattr(exc, "read", None)
        if not callable(reader):
            return ""
        raw = reader()
    except Exception:  # noqa: BLE001
        return ""
    if not raw:
        return ""
    try:
        if isinstance(raw, (bytes, bytearray)):
            text = bytes(raw).decode("utf-8", errors="replace")
        else:
            text = str(raw)
    except Exception:  # noqa: BLE001
        return ""
    text = text.strip()
    if not text:
        return ""
    try:
        parsed = json.loads(text)
    except (ValueError, TypeError):
        return f" — {text[:240]}"
    if isinstance(parsed, dict):
        inner = parsed.get("error")
        if isinstance(inner, str) and inner.strip():
            return f" — {inner.strip()[:240]}"
    return ""


def _build_error(
    config: LLMConfig | None,
    prompt_chars: int,
    error: str,
    elapsed_ms: int,
) -> LLMResponse:
    return LLMResponse(
        ok=False,
        backend=config.backend_type if config else "",
        model=config.model_name if config else "",
        endpoint=config.endpoint_url if config else "",
        timestamp=_now_timestamp(),
        response_text="",
        error=error,
        elapsed_ms=elapsed_ms,
        prompt_chars=prompt_chars,
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def generate_llm_response(
    prompt_payload: LLMPromptPayload,
    config: LLMConfig | None = None,
    *,
    transport: Transport | None = None,
) -> LLMResponse:
    """Send a prompt to the local LLM and return its plain-text response.

    Never raises. All failures are surfaced via :class:`LLMResponse` with
    ``ok=False`` and a deterministic ``error`` string.

    Args:
        prompt_payload: The output of ``build_llm_prompt(...)``. The adapter
            only reads ``prompt_payload.prompt_text`` — no other fields are
            transmitted.
        config: An :class:`LLMConfig`. If omitted, env-driven config is
            loaded via :func:`load_config_from_env`.
        transport: Optional injectable transport for tests. Production code
            should leave this as ``None``.
    """
    started = time.perf_counter()

    if config is None:
        try:
            config = load_config_from_env()
        except Exception as exc:  # noqa: BLE001
            return LLMResponse(
                ok=False,
                backend="",
                model="",
                endpoint="",
                timestamp=_now_timestamp(),
                response_text="",
                error=f"config_error: {exc}",
                elapsed_ms=0,
                prompt_chars=0,
            )

    if not isinstance(prompt_payload, LLMPromptPayload):
        return _build_error(
            config, 0, "invalid_payload: expected LLMPromptPayload", 0
        )

    if config.backend_type not in SUPPORTED_BACKENDS:
        return _build_error(
            config,
            len(prompt_payload.prompt_text),
            f"unsupported_backend: {config.backend_type}",
            0,
        )

    if config.backend_type == "openrouter":
        ok, reason = _is_openrouter_endpoint(config.endpoint_url)
    else:
        ok, reason = _is_local_endpoint(config.endpoint_url)
    if not ok:
        return _build_error(
            config,
            len(prompt_payload.prompt_text),
            f"endpoint_rejected: {reason}",
            0,
        )

    active_transport: Transport = transport if transport is not None else _http_post
    prompt_text = prompt_payload.prompt_text

    try:
        if config.backend_type == "ollama":
            response_text = _call_ollama(prompt_text, config, active_transport)
        elif config.backend_type == "openai_compatible":
            response_text = _call_openai_compat(
                prompt_text, config, active_transport
            )
        else:  # openrouter
            if transport is not None:
                response_text = _call_openai_compat(prompt_text, config, active_transport)
            else:
                response_text = _call_openrouter(prompt_text, config)
    except urllib.error.HTTPError as exc:
        elapsed = int((time.perf_counter() - started) * 1000)
        return _build_error(
            config,
            len(prompt_text),
            f"http_error: {exc.code} {exc.reason}{_read_http_error_body(exc)}",
            elapsed,
        )
    except urllib.error.URLError as exc:
        elapsed = int((time.perf_counter() - started) * 1000)
        return _build_error(
            config,
            len(prompt_text),
            f"connection_failure: {exc.reason}",
            elapsed,
        )
    except (socket.timeout, TimeoutError):
        elapsed = int((time.perf_counter() - started) * 1000)
        # Embed the configured timeout in the token so the response panel
        # can render ``Local model request timed out after <N> seconds.``
        # without needing a new field on ``LLMResponse``. Existing tests
        # that asserted on the ``timeout`` prefix keep working.
        try:
            n = int(round(float(config.timeout_seconds)))
        except (TypeError, ValueError):
            n = 0
        token = f"timeout: {n}" if n > 0 else "timeout"
        return _build_error(config, len(prompt_text), token, elapsed)
    except json.JSONDecodeError as exc:
        elapsed = int((time.perf_counter() - started) * 1000)
        return _build_error(
            config, len(prompt_text), f"invalid_json: {exc}", elapsed
        )
    except ValueError as exc:
        elapsed = int((time.perf_counter() - started) * 1000)
        return _build_error(
            config, len(prompt_text), f"malformed_response: {exc}", elapsed
        )
    except Exception as exc:  # noqa: BLE001
        elapsed = int((time.perf_counter() - started) * 1000)
        return _build_error(
            config,
            len(prompt_text),
            f"unexpected_error: {type(exc).__name__}: {exc}",
            elapsed,
        )

    elapsed = int((time.perf_counter() - started) * 1000)
    return LLMResponse(
        ok=True,
        backend=config.backend_type,
        model=config.model_name,
        endpoint=config.endpoint_url,
        timestamp=_now_timestamp(),
        response_text=response_text,
        error=None,
        elapsed_ms=elapsed,
        prompt_chars=len(prompt_text),
    )


def probe_endpoint(config: LLMConfig, timeout: float = 2.0) -> dict[str, Any]:
    """TCP-probe the local LLM endpoint without sending any prompt.

    Used by validation harnesses to decide whether to call the live runtime
    or fall back to a mocked transport. Does not transmit any model payload.
    Returns a dict with ``alive`` (bool), ``latency_ms`` (int), ``error``
    (str | None).
    """
    started = time.perf_counter()
    if config.backend_type == "openrouter":
        ok, reason = _is_openrouter_endpoint(config.endpoint_url)
        if not ok:
            return {
                "alive": False,
                "latency_ms": 0,
                "error": f"endpoint_rejected: {reason}",
            }
        return {
            "alive": bool(config.api_key),
            "latency_ms": 0,
            "error": None if config.api_key else "missing_openrouter_api_key",
        }
    ok, reason = _is_local_endpoint(config.endpoint_url)
    if not ok:
        return {
            "alive": False,
            "latency_ms": 0,
            "error": f"endpoint_rejected: {reason}",
        }
    parsed = urlparse(config.endpoint_url)
    host = parsed.hostname or "localhost"
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    try:
        with socket.create_connection((host, port), timeout=timeout):
            pass
        return {
            "alive": True,
            "latency_ms": int((time.perf_counter() - started) * 1000),
            "error": None,
        }
    except OSError as exc:
        return {
            "alive": False,
            "latency_ms": int((time.perf_counter() - started) * 1000),
            "error": f"{type(exc).__name__}: {exc}",
        }
