"""HTML observation comparison table for the MM.AI workspace.

Renders one or more observation dicts (from
:func:`src.observation_builder.build_observations`) as a side-by-side
``Parameter | Previous | Latest | Delta`` table per symbol. The output is
plain HTML so a ``QTextBrowser`` can render it with horizontal overflow
when the symbol set is wider than the viewport.

This module performs no analysis, narrative, or prediction — it only
reshapes existing observation fields into a comparison grid.
"""

from __future__ import annotations

import math
from datetime import datetime
from html import escape
from typing import Any

from .text_formatter import NA, TIMESTAMP_FORMAT
from .ui.theme import PALETTE

# (display_label, previous_key, latest_key, delta_key, kind)
# previous_key=None  → no "Previous" cell (e.g. one-shot deltas like Chg-in-OI)
# delta_key=None     → no "Delta" cell (text fields or one-shot values)
# kind: "num" | "text"
_RowSpec = tuple[str, str | None, str, str | None, str]

CASH_ROWS: list[_RowSpec] = [
    ("Session", "previous_session", "latest_session", None, "text"),
    ("Close", "previous_close", "latest_close", "close_delta", "num"),
    ("Volume", "previous_volume", "latest_volume", "volume_delta", "num"),
    ("Delivery Qty", "previous_delivery_qty", "latest_delivery_qty", "delivery_qty_delta", "num"),
    ("Delivery %", "previous_delivery_percent", "latest_delivery_percent", "delivery_percent_delta", "num"),
]

FO_ROWS: list[_RowSpec] = [
    ("Session", "previous_session", "latest_session", None, "text"),
    ("OI Total", "previous_oi_total", "latest_oi_total", "oi_delta", "num"),
    ("Chg in OI", None, "latest_chg_in_oi_total", None, "num"),
    ("Contracts", "previous_contracts_total", "latest_contracts_total", "contracts_delta", "num"),
]

EMDASH = "—"


def _fmt_num(value: Any) -> str:
    if value is None:
        return NA
    try:
        out = float(value)
    except (TypeError, ValueError):
        return NA
    if math.isnan(out) or math.isinf(out):
        return NA
    return str(round(out, 6))


def _fmt_text(value: Any) -> str:
    if value is None or value == "":
        return NA
    return str(value)


def _fmt_signed_delta(value: Any) -> str:
    if value is None:
        return NA
    try:
        out = float(value)
    except (TypeError, ValueError):
        return NA
    if math.isnan(out) or math.isinf(out):
        return NA
    rounded = round(out, 6)
    if rounded > 0:
        return f"+{rounded}"
    return str(rounded)


def _delta_class(value: Any) -> str:
    """Return CSS class hint for delta colouring. Deterministic, not predictive."""
    if value is None:
        return "neutral"
    try:
        out = float(value)
    except (TypeError, ValueError):
        return "neutral"
    if math.isnan(out) or math.isinf(out):
        return "neutral"
    if out > 0:
        return "pos"
    if out < 0:
        return "neg"
    return "neutral"


def _build_css() -> str:
    p = PALETTE
    return f"""<style>
body, .obs-wrap {{
    color: {p['text_primary']};
    font-family: 'Segoe UI', 'Inter', sans-serif;
}}
.obs-meta {{
    color: {p['text_secondary']};
    font-family: Consolas, 'Cascadia Mono', monospace;
    padding: 0 0 2px 0;
}}
.section-label {{
    color: {p['text_secondary']};
    font-weight: 700;
    letter-spacing: 2px;
    padding: 4px 0 2px 0;
    font-size: 9pt;
}}
table.obs {{
    border-collapse: collapse;
    font-family: Consolas, 'Cascadia Mono', monospace;
    font-size: 10pt;
    margin-bottom: 6px;
}}
table.obs th, table.obs td {{
    padding: 3px 10px;
    border-bottom: 1px solid {p['border']};
    white-space: nowrap;
}}
table.obs th.symbol {{
    color: {p['accent']};
    text-align: center;
    letter-spacing: 1px;
    border-bottom: 1px solid {p['border']};
    background-color: {p['header_bg']};
}}
table.obs th.subhdr {{
    color: {p['text_secondary']};
    text-align: right;
    font-weight: 600;
}}
table.obs th.parahdr {{
    color: {p['text_secondary']};
    text-align: left;
    font-weight: 600;
}}
table.obs td.param {{
    color: {p['text_secondary']};
    text-align: left;
}}
table.obs td.num {{
    color: {p['text_primary']};
    text-align: right;
}}
table.obs td.pos {{ color: #34D399; }}
table.obs td.neg {{ color: #F87171; }}
table.obs td.neutral {{ color: {p['text_secondary']}; }}
table.obs tr.colgroup-sep td {{
    background-color: {p['header_bg']};
}}
</style>"""


def _render_section(
    section_label: str,
    rows: list[_RowSpec],
    observations: list[dict[str, Any]],
    source_key: str,
) -> str:
    out: list[str] = []
    out.append(f'<div class="section-label">{escape(section_label)}</div>')
    out.append('<table class="obs" cellspacing="0" cellpadding="0">')

    out.append("<tr>")
    out.append('<th class="parahdr" rowspan="2">Parameter</th>')
    for obs in observations:
        sym = escape(obs.get("symbol") or NA)
        out.append(f'<th class="symbol" colspan="3">{sym}</th>')
    out.append("</tr>")

    out.append("<tr>")
    for _ in observations:
        out.append(
            '<th class="subhdr">Previous</th>'
            '<th class="subhdr">Latest</th>'
            '<th class="subhdr">&Delta;</th>'
        )
    out.append("</tr>")

    for label, prev_key, latest_key, delta_key, kind in rows:
        out.append(f'<tr><td class="param">{escape(label)}</td>')
        for obs in observations:
            section = obs.get(source_key) or {}
            if kind == "text":
                prev_str = _fmt_text(section.get(prev_key)) if prev_key else EMDASH
                latest_str = _fmt_text(section.get(latest_key))
                delta_str = EMDASH
                delta_cls = "neutral"
            else:
                prev_str = _fmt_num(section.get(prev_key)) if prev_key else EMDASH
                latest_str = _fmt_num(section.get(latest_key))
                if delta_key:
                    delta_raw = section.get(delta_key)
                    delta_str = _fmt_signed_delta(delta_raw)
                    delta_cls = _delta_class(delta_raw)
                else:
                    delta_str = EMDASH
                    delta_cls = "neutral"
            out.append(f'<td class="num">{escape(prev_str)}</td>')
            out.append(f'<td class="num">{escape(latest_str)}</td>')
            out.append(f'<td class="num {delta_cls}">{escape(delta_str)}</td>')
        out.append("</tr>")
    out.append("</table>")
    return "".join(out)


def render_observation_html(observations: list[dict[str, Any]]) -> str:
    """Render a comparison HTML table for one or more observation dicts.

    Empty input renders a stub block with the timestamp and an explicit
    ``no symbols loaded`` notice. No analytics are computed; only
    pre-built observation fields are reshaped.
    """
    now = datetime.now().strftime(TIMESTAMP_FORMAT)
    parts: list[str] = [_build_css(), '<div class="obs-wrap">']
    if not observations:
        parts.append(
            f'<div class="obs-meta">[{escape(now)}] &middot; no symbols loaded</div>'
        )
        parts.append("</div>")
        return "".join(parts)

    sym_summary = ", ".join(escape(obs.get("symbol") or NA) for obs in observations)
    parts.append(
        f'<div class="obs-meta">[{escape(now)}] &middot; {len(observations)} '
        f'symbol(s): {sym_summary}</div>'
    )
    parts.append(_render_section("CASH", CASH_ROWS, observations, "cash"))
    parts.append(_render_section("F&O", FO_ROWS, observations, "fo"))
    parts.append("</div>")
    return "".join(parts)
