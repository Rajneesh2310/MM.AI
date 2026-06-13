"""Deterministic observation-to-text formatter for MM.AI.

Converts the dict produced by :func:`src.observation_builder.build_observations`
into a plain-text block. Output contains only factual values, deterministic
deltas, and explicit session references. No interpretation, narrative,
prediction, classification, or recommendation is produced.

Null values render as ``Not Available``.
Floating-point arithmetic artefacts are normalised by rounding to 6
fractional digits at *format* time only (the underlying observation data is
not mutated).
"""

from __future__ import annotations

import math
from datetime import datetime
from typing import Any

TIMESTAMP_FORMAT = "%d:%m:%y %H:%M:%S"
NA = "Not Available"


def _now_timestamp() -> str:
    return datetime.now().strftime(TIMESTAMP_FORMAT)


def _format_float(value: Any) -> str:
    if value is None:
        return NA
    try:
        out = float(value)
    except (TypeError, ValueError):
        return NA
    if math.isnan(out) or math.isinf(out):
        return NA
    return str(round(out, 6))


def _format_int(value: Any) -> str:
    if value is None:
        return NA
    try:
        return str(int(value))
    except (TypeError, ValueError):
        return NA


def _format_text(value: Any) -> str:
    if value is None or value == "":
        return NA
    return str(value)


def _emit(lines: list[str], label: str, value: str) -> None:
    lines.append(f"{label}:")
    lines.append(value)
    lines.append("")


def _section_header(lines: list[str], header: str) -> None:
    lines.append(header)
    lines.append("")


def _format_cash(lines: list[str], cash: dict[str, Any]) -> None:
    _section_header(lines, "CASH")
    _emit(lines, "Latest Session", _format_text(cash.get("latest_session")))
    _emit(lines, "Previous Session", _format_text(cash.get("previous_session")))
    _emit(lines, "Latest Close", _format_float(cash.get("latest_close")))
    _emit(lines, "Previous Close", _format_float(cash.get("previous_close")))
    _emit(lines, "Close Delta", _format_float(cash.get("close_delta")))
    _emit(lines, "Latest Volume", _format_float(cash.get("latest_volume")))
    _emit(lines, "Previous Volume", _format_float(cash.get("previous_volume")))
    _emit(lines, "Volume Delta", _format_float(cash.get("volume_delta")))
    _emit(lines, "Latest Delivery Qty", _format_float(cash.get("latest_delivery_qty")))
    _emit(lines, "Previous Delivery Qty", _format_float(cash.get("previous_delivery_qty")))
    _emit(lines, "Delivery Qty Delta", _format_float(cash.get("delivery_qty_delta")))
    _emit(lines, "Latest Delivery Percent", _format_float(cash.get("latest_delivery_percent")))
    _emit(lines, "Previous Delivery Percent", _format_float(cash.get("previous_delivery_percent")))
    _emit(lines, "Delivery Percent Delta", _format_float(cash.get("delivery_percent_delta")))


def _format_fo(lines: list[str], fo: dict[str, Any]) -> None:
    _section_header(lines, "F&O")
    _emit(lines, "Latest Session", _format_text(fo.get("latest_session")))
    _emit(lines, "Previous Session", _format_text(fo.get("previous_session")))
    _emit(lines, "Latest F&O Row Count", _format_int(fo.get("latest_fo_row_count")))
    _emit(lines, "Previous F&O Row Count", _format_int(fo.get("previous_fo_row_count")))
    _emit(lines, "Latest OI Total", _format_float(fo.get("latest_oi_total")))
    _emit(lines, "Previous OI Total", _format_float(fo.get("previous_oi_total")))
    _emit(lines, "OI Delta", _format_float(fo.get("oi_delta")))
    _emit(lines, "Latest Chg In OI Total", _format_float(fo.get("latest_chg_in_oi_total")))
    _emit(lines, "Latest Contracts Total", _format_float(fo.get("latest_contracts_total")))
    _emit(lines, "Previous Contracts Total", _format_float(fo.get("previous_contracts_total")))
    _emit(lines, "Contracts Delta", _format_float(fo.get("contracts_delta")))


def format_observations(observation_data: dict[str, Any]) -> str:
    """Render an observation dict as a plain-text deterministic block.

    Parameters
    ----------
    observation_data:
        Output dict from :func:`build_observations`. Missing keys are tolerated
        and render as ``Not Available``.

    Returns
    -------
    str
        Plain text containing only factual fields, in the order documented in
        the MM.AI text-formatter spec. Ends with a single trailing newline.
    """
    if not isinstance(observation_data, dict):
        raise TypeError("observation_data must be a dict")

    lines: list[str] = []
    lines.append(f"[{_now_timestamp()}]")
    lines.append("")
    lines.append(f"SYMBOL: {_format_text(observation_data.get('symbol'))}")
    lines.append("")

    _format_cash(lines, observation_data.get("cash") or {})
    _format_fo(lines, observation_data.get("fo") or {})

    text = "\n".join(lines).rstrip() + "\n"
    return text
