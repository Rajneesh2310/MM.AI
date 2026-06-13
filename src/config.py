"""MM install / data root resolution for MM.AI.

Read-only. Resolves the directory that owns ``cash`` and ``fo`` so the symbol
reader can locate parquet shards without depending on the MM backend.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

DATA_ENV_VAR = "MM_DATA_ROOT"
ENV_VAR = "MM_INSTALL_ROOT"
VPS_DATA_ROOT = Path("/opt/mm-web-data")
_DEV_DEFAULT = Path.home() / "MMMarket"
_FROZEN_CONFIG_NAME = "mm_install.json"


def _frozen_install_root() -> Path | None:
    if not getattr(sys, "frozen", False):
        return None
    cfg = Path(sys.executable).resolve().parent / _FROZEN_CONFIG_NAME
    if not cfg.is_file():
        return None
    try:
        raw = json.loads(cfg.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    root = raw.get("install_root") or raw.get("data_root") if isinstance(raw, dict) else None
    if not root:
        return None
    try:
        return Path(str(root)).expanduser().resolve()
    except (OSError, ValueError):
        return None


def install_root() -> Path:
    """Resolve the MM installation root.

    Order: ``MM_INSTALL_ROOT`` env var, ``mm_install.json`` beside frozen exe,
    then ``~/MMMarket``. For VPS/web deployments prefer :func:`data_root`
    with ``MM_DATA_ROOT`` because the web app uses a direct data-folder path.
    """
    env = os.environ.get(ENV_VAR, "").strip()
    if env:
        return Path(env).expanduser().resolve()
    frozen = _frozen_install_root()
    if frozen is not None:
        return frozen
    return _DEV_DEFAULT.resolve()


def data_root() -> Path:
    env = os.environ.get(DATA_ENV_VAR, "").strip()
    if env:
        return Path(env).expanduser().resolve()
    if os.name != "nt":
        return VPS_DATA_ROOT
    return install_root() / "data"


def cash_root() -> Path:
    return data_root() / "cash"


def fo_root() -> Path:
    return data_root() / "fo"
