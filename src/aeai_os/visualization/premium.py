"""Self-contained, CSP-friendly, printable enterprise intelligence documents.

The content in these documents is sourced from existing deterministic analysis
artifacts. There are no external fonts/scripts and no network dependencies.
"""

from __future__ import annotations

import json
import math
from collections.abc import Iterable
from html import escape
from typing import Any

from aeai_os.visualization.dashboard import ProcurementChartSpec

CSS = r"""
:root{--ink:#182138;--sub:#66738d;--line:#e5eaf2;--bg:#f5f7fb;--paper:#fff;--navy:#121a31;--indigo:#5b5ceb;--teal:#009f89;--orange:#d88732;--pink:#d34668;--radius:18px}
*{box-sizing:border-box}html{scroll-behavior:smooth}body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.6 -apple-system,BlinkMacSystemFont,"Segoe UI",Inter,Arial,sans-serif;-webkit-font-smoothing:antialiased}
a{color:inherit;text-decoration:none}a:focus-visible{outline:3px solid #a8a9fa;outline-offset:4px}h1,h2,h3,p{margin-top:0}h1,h2,h3{line-height:1.2;letter-spacing:-.035em}svg{max-width:100%;height:auto;display:block}table{border-collapse:collapse;width:100%}th,td{text-align:left;padding:12px 13px;border-bottom:1px solid var(--line);vertical-align:top}th{font-size:10px;letter-spacing:.12em;color:#6c7a95;text-transform:uppercase;font-weight:800;background:#f7f9fd;white-space:nowrap}td{font-size:12px;overflow-wrap:anywhere}tr:last-child td{border-bottom:0}tbody tr:hover{background:#fafbfe}
.shell{display:grid;grid-template-columns:236px minmax(0,1fr);min-height:100vh}.rail{background:var(--navy);color:#bfc9df;padding:27px 20px;position:sticky;top:0;height:100vh;overflow:auto;display:flex;flex-direction:column;gap:36px}.brand{display:flex;align-items:center;gap:12px;font-size:12px;color:#fff;letter-spacing:.06em;font-weight:850}.brand-mark{display:grid;place-items:center;width:39px;height:39px;background:linear-gradient(135deg,#897afe,#35d8b6);border-radius:13px;color:white;font-size:21px;font-weight:800;box-shadow:0 8px 25px #202756}.rail-label{margin:0 0 13px;color:#7e91b7;font-size:10px;letter-spacing:.15em;text-transform:uppercase;font-weight:800}.rail nav{display:grid;gap:4px}.rail nav a{display:flex;align-items:center;gap:12px;padding:10px 12px;border-radius:10px;color:#b9c5da;font-size:12px;transition:background .15s}.rail nav a:before{content:'';width:5px;height:5px;border-radius:100%;background:#626f91}.rail nav a:hover{background:#283655;color:#fff}.rail-tip{margin-top:auto;border:1px solid #3c4867;background:#202b45;padding:16px;border-radius:13px;font-size:11px;line-height:1.7}.rail-tip strong{color:#fff;display:block;font-size:12px;margin-bottom:4px}.work{min-width:0;padding:0 40px 64px}.topbar{height:74px;border-bottom:1px solid var(--line);display:flex;justify-content:space-between;align-items:center;gap:16px}.topbar-path{font-size:12px;font-weight:750;color:#68758f}.topbar-path b{color:var(--ink)}.topbar-actions{display:flex;gap:9px;align-items:center}.tiny-tag{background:#e9f8f5;border:1px solid #ccebe4;color:#047f70;padding:6px 11px;border-radius:99px;font-size:10px;font-weight:800;letter-spacing:.06em;text-transform:uppercase}.print-link{background:#fff;border:1px solid #dce3ee;border-radius:9px;font-size:11px;padding:8px 11px;font-weight:750}.print-link:hover{border-color:#7374e9;color:#4a4bd7}.content{width:min(1210px,100%);margin:auto}.hero{padding:37px 39px 35px;border-radius:22px;background:radial-gradient(ellipse at 92% 0%,#38426f 0%,transparent 42%),linear-gradient(123deg,#131c34,#222b4b);color:white;margin-top:26px;position:relative;overflow:hidden}.hero:after{content:'';position:absolute;width:235px;height:235px;border:1px solid #ffffff15;border-radius:50%;right:-58px;bottom:-126px;box-shadow:0 0 0 46px #ffffff08,0 0 0 95px #ffffff04;pointer-events:none}.hero .eyebrow{color:#b6c0ff}.eyebrow{text-transform:uppercase;font-size:10px;font-weight:850;letter-spacing:.17em;color:var(--indigo);display:block;margin-bottom:12px}.hero h1{font-size:clamp(30px,3.6vw,50px);letter-spacing:-.052em;margin-bottom:14px;max-width:760px;line-height:1.09}.hero p{color:#c2cbde;max-width:680px;font-size:13px;margin-bottom:24px;line-height:1.8}.hero-meta{display:flex;flex-wrap:wrap;gap:9px}.hero-meta span{font-size:10px;font-weight:750;color:#dbe3f6;padding:7px 11px;border:1px solid #8996bf4d;border-radius:9px;background:#ffffff0b}.hero-meta .confidence{color:#86e5ce;border-color:#7cdbbc50}.section-label{display:flex;align-items:center;justify-content:space-between;margin:31px 0 14px;gap:16px}.section-label h2{font-size:21px;margin:0;letter-spacing:-.04em}.section-label span{color:#8b96ab;font-size:11px}.stat-grid{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:12px}.stat{padding:20px 21px;background:#fff;border:1px solid var(--line);border-radius:15px;min-width:0;box-shadow:0 6px 23px #1b285008}.stat .label{color:#7a879c;font-size:10px;letter-spacing:.04em;font-weight:800;display:block}.stat .value{display:block;font-size:clamp(20px,2vw,29px);font-weight:820;letter-spacing:-.045em;white-space:normal;overflow-wrap:anywhere;line-height:1.3;margin:12px 0 5px}.stat .hint{font-size:10px;color:#98a3b6}.stat:nth-child(2) .value{color:#4c58d9}.stat:nth-child(3) .value{color:#d58b42}.stat:nth-child(4) .value{color:#008b7b}
.two{display:grid;grid-template-columns:minmax(0,1.18fr) minmax(0,1fr);gap:17px}.card{background:#fff;border:1px solid var(--line);border-radius:17px;box-shadow:0 7px 30px #1c2a4a05;min-width:0;overflow:hidden}.pad{padding:25px}.card-title{display:flex;justify-content:space-between;align-items:flex-start;gap:10px;margin-bottom:17px}.card-title h3{margin:0;font-size:16px;letter-spacing:-.035em}.card-title p{margin:5px 0 0;color:var(--sub);font-size:11px;line-height:1.6}.card-title .mark{font-size:9px;text-transform:uppercase;letter-spacing:.1em;color:#6064d7;font-weight:850;background:#efefff;padding:6px 8px;border-radius:7px;white-space:nowrap}.section-card{margin-top:16px}.insight-list{display:grid;gap:11px;list-style:none;padding:0;margin:0}.insight-list li{border-left:3px solid #9c9aff;background:#f9faff;border-radius:0 9px 9px 0;padding:11px 14px;font-size:12px;color:#43506a}.insight-list li:first-child{border-color:#36b7a0}.mini-note{font-size:11px;color:#8492a8;margin:12px 0 0}.chart-graphic{width:100%}.chart-svg{width:100%;height:auto}.axis-label{font-size:10px;fill:#8390aa;font-weight:600}.grid-line{stroke:#e9edf5;stroke-width:1}.bar-list{display:grid;gap:14px;margin-top:12px}.bar-labels{display:flex;justify-content:space-between;gap:8px;font-size:11px;margin-bottom:5px}.bar-name{font-weight:760;color:#333e58;max-width:65%;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.bar-value{font-weight:800;color:#3b4660;white-space:nowrap}.bar-track{height:9px;background:#eef1f7;border-radius:99px;overflow:hidden}.bar-fill{height:100%;border-radius:99px;background:linear-gradient(90deg,#7775ff,#514ecc)}.bar-row:nth-child(even) .bar-fill{background:linear-gradient(90deg,#3fc5b6,#039e90)}.bar-sub{font-size:10px;color:#8895ab;margin-top:4px}.pill{display:inline-block;border-radius:6px;font-size:9px;font-weight:850;letter-spacing:.05em;text-transform:uppercase;padding:4px 8px}.pill-critical{background:#fee5e9;color:#a21c3a}.pill-high{background:#fff0df;color:#9d5d13}.pill-medium{background:#fff8df;color:#98731f}.pill-low{background:#e3f5ee;color:#167c64}.pill-neutral{background:#eef1fa;color:#627089}.riskbar{height:6px;background:#edf0f7;border-radius:4px;min-width:90px;margin-top:7px}.riskbar span{display:block;height:100%;background:#ef9474;border-radius:4px}.table-scroll{width:100%;overflow-x:auto}.table-scroll table{min-width:620px}.table-scroll.compact table{min-width:470px}.no-data{padding:25px;background:#f7f9fd;border:1px dashed #dbe2ee;border-radius:12px;font-size:12px;color:var(--sub)}.chart-caption{color:#8793a7;font-size:10px;margin:12px 0 0}.callout{display:flex;gap:12px;background:#eef8f6;border:1px solid #d3ede7;padding:15px 17px;border-radius:12px;color:#28675e;font-size:12px;line-height:1.7}.callout .icon{font-size:17px;line-height:1}.recommendations{display:grid;gap:10px}.rec{display:flex;gap:14px;padding:14px 0;border-bottom:1px solid #eff2f8}.rec:last-child{border:0}.rec-n{flex:none;color:#7277dd;font-weight:900;font-size:12px}.rec p{font-size:12px;line-height:1.7;color:#4c5a73;margin:0}.rec strong{font-weight:800}.method-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:13px}.method{padding:13px;background:#f6f8fc;border:1px solid #edf1f7;border-radius:10px}.method label{display:block;color:#8b98ab;font-size:10px;font-weight:800}.method strong{display:block;margin-top:4px;font-size:12px;overflow-wrap:anywhere}.footer{display:flex;justify-content:space-between;gap:20px;border-top:1px solid var(--line);margin-top:39px;padding-top:20px;color:#93a0b3;font-size:10px}.detail{font-size:12px;color:#53627c;line-height:1.75}.detail h3{font-size:12px;margin:18px 0 7px;letter-spacing:-.01em}.detail ul{margin:0;padding-left:20px}.detail li{margin:5px 0}.chart-full{margin-top:20px}.chart-full .card{padding:27px}.section-anchor{scroll-margin-top:18px}.tint-label{font-weight:850;color:#5865c7;font-size:10px;letter-spacing:.1em;text-transform:uppercase}.data-signal{color:#7e8ba2;font-size:10px;margin:6px 0 0}.full-width{grid-column:1/-1}.badge-small{background:#e9f7f3;color:#0b8879;padding:5px 8px;border-radius:7px;font-weight:850;font-size:10px}.ledger{display:flex;gap:7px;flex-wrap:wrap}.ledger code{font-family:ui-monospace,SFMono-Regular,monospace;font-size:9px;color:#6d7894;background:#f1f3f9;padding:6px 8px;border-radius:6px;overflow-wrap:anywhere}.chart-page .hero{margin-top:24px}.chart-page .chart-full{margin-top:20px}.chart-page .stat-grid{grid-template-columns:repeat(3,minmax(0,1fr))}
@media(max-width:1160px){.shell{grid-template-columns:200px minmax(0,1fr)}.work{padding:0 25px 48px}.stat-grid{grid-template-columns:repeat(2,minmax(0,1fr))}}@media(max-width:790px){.shell{display:block}.rail{position:static;height:auto;padding:13px 19px;gap:13px}.rail .rail-label,.rail .rail-tip{display:none}.rail nav{display:flex;overflow:auto;gap:8px}.rail nav a{flex:none;padding:7px 10px;background:#202b45}.rail nav a:before{display:none}.work{padding:0 15px 45px}.topbar{height:58px}.hero{padding:26px 24px}.two{grid-template-columns:1fr}.stat-grid{grid-template-columns:repeat(2,minmax(0,1fr))}.pad{padding:18px}.footer{flex-direction:column;gap:7px}}@media(max-width:430px){.hero h1{font-size:29px}.stat{padding:15px}.stat .value{font-size:20px}.topbar-actions .tiny-tag{display:none}.method-grid{grid-template-columns:1fr}.section-label h2{font-size:19px}}@media print{@page{size:A4;margin:11mm}html,body{background:white!important;-webkit-print-color-adjust:exact;print-color-adjust:exact}.shell{display:block}.rail,.topbar-actions{display:none}.work{padding:0}.content{max-width:100%}.topbar{height:35px}.hero{margin-top:10px;border-radius:12px;padding:22px 25px}.hero h1{font-size:28px}.stat-grid{grid-template-columns:repeat(4,minmax(0,1fr))}.stat{padding:10px;box-shadow:none}.stat .value{font-size:18px}.two{grid-template-columns:1fr 1fr}.card{box-shadow:none}.card,.section-card,.stat,.bar-row,tr{break-inside:avoid}.section-label{break-after:avoid}.footer{margin-top:20px}body{font-size:12px}}
"""  # noqa: E501


# Both standalone generated HTML and the integrated artifact viewer use the
# exact same theme tokens. Print deliberately switches to high-contrast paper.
DARK_CSS = r"""
:root[data-theme="dark"] {
  color-scheme: dark;
  --ink: #e9eefb;
  --sub: #a0b0cb;
  --line: #29364e;
  --bg: #090e19;
  --paper: #111929;
  --navy: #0b1322;
  --indigo: #a4a1ff;
}
[data-theme="dark"] body {background:var(--bg);color:var(--ink)}
[data-theme="dark"] .rail {background:#0c1524;border-right:1px solid #26334a}
[data-theme="dark"] .rail nav a:hover {background:#25334c}
[data-theme="dark"] .rail-tip {background:#17243a;border-color:#30435e}
[data-theme="dark"] .topbar {border-color:var(--line)}
[data-theme="dark"] .topbar-path {color:#90a3c0}
[data-theme="dark"] .tiny-tag {background:#153a39;border-color:#286660;color:#73e1cc}
[data-theme="dark"] .print-link {background:#152237;border-color:#34445f;color:#d5dcf1}
[data-theme="dark"] .print-link:hover {border-color:#8881f7;color:#fff}
[data-theme="dark"] .hero {background:radial-gradient(ellipse at 91% 0%,#334468 0%,transparent 45%),linear-gradient(125deg,#172641,#111c31);border:1px solid #34435b}
[data-theme="dark"] .hero p {color:#c4d1e5}
[data-theme="dark"] .stat, [data-theme="dark"] .card {background:#121c2d;border-color:var(--line);box-shadow:0 12px 30px #00000028}
[data-theme="dark"] .stat .label, [data-theme="dark"] .stat .hint {color:#9aa9c0}
[data-theme="dark"] .stat .value {color:#f0f4ff}
[data-theme="dark"] .stat:nth-child(2) .value {color:#a7a8ff}
[data-theme="dark"] .stat:nth-child(3) .value {color:#ffcc8b}
[data-theme="dark"] .stat:nth-child(4) .value {color:#64ddc4}
[data-theme="dark"] .section-label span, [data-theme="dark"] .card-title p {color:#9dacc5}
[data-theme="dark"] .card-title .mark {color:#c9c7ff;background:#2a2852}
[data-theme="dark"] th {background:#1b283c;color:#acbbd4}
[data-theme="dark"] td {color:#d6dff0}
[data-theme="dark"] tbody tr:hover {background:#1b293d}
[data-theme="dark"] .insight-list li {background:#1b2941;color:#d0daf0;border-color:#827cf9}
[data-theme="dark"] .insight-list li:first-child {border-color:#53c9ae}
[data-theme="dark"] .bar-name, [data-theme="dark"] .bar-value {color:#e5edfa}
[data-theme="dark"] .bar-track {background:#26334a}
[data-theme="dark"] .bar-sub, [data-theme="dark"] .chart-caption, [data-theme="dark"] .data-signal {color:#97a8c2}
[data-theme="dark"] .axis-label {fill:#a2b1cb}
[data-theme="dark"] .grid-line {stroke:#2e3d57}
[data-theme="dark"] .riskbar {background:#283750}
[data-theme="dark"] .pill-critical {background:#592938;color:#ffadbc}
[data-theme="dark"] .pill-high {background:#4b3427;color:#ffd19c}
[data-theme="dark"] .pill-medium {background:#51462a;color:#ffe4a0}
[data-theme="dark"] .pill-low {background:#1a433f;color:#83e8c8}
[data-theme="dark"] .pill-neutral {background:#273650;color:#b0bfd9}
[data-theme="dark"] .no-data {background:#162339;border-color:#34445f;color:#a5b6cd}
[data-theme="dark"] .callout {background:#183a39;border-color:#2a6259;color:#b0f1de}
[data-theme="dark"] .rec {border-color:#2b3a53}
[data-theme="dark"] .rec p, [data-theme="dark"] .detail {color:#c9d6ea}
[data-theme="dark"] .method {background:#1a273c;border-color:#2a3a54}
[data-theme="dark"] .method label, [data-theme="dark"] .mini-note {color:#a0aec6}
[data-theme="dark"] .ledger code {background:#24324b;color:#c2cde3}
[data-theme="dark"] .footer {color:#9ba9be}

/* The PDF is always a readable, white-paper document, independent of UI theme. */
@media print {
  :root[data-theme="dark"] {color-scheme:light;--ink:#182138;--sub:#66738d;--line:#e5eaf2;--bg:#fff;--paper:#fff;--indigo:#5b5ceb}
  [data-theme="dark"] body {background:#fff!important;color:#182138!important}
  [data-theme="dark"] .topbar, [data-theme="dark"] .footer {border-color:#e5eaf2;color:#66738d}
  [data-theme="dark"] .topbar-path {color:#66738d}
  [data-theme="dark"] .stat, [data-theme="dark"] .card {background:#fff!important;border-color:#e2e8f2;box-shadow:none}
  [data-theme="dark"] .stat .label, [data-theme="dark"] .stat .hint {color:#66738d!important}
  [data-theme="dark"] .stat .value {color:#182138!important}
  [data-theme="dark"] .section-label span, [data-theme="dark"] .card-title p {color:#66738d}
  [data-theme="dark"] .card-title .mark {background:#f0efff;color:#5553be}
  [data-theme="dark"] th {background:#f4f6fb!important;color:#61718e!important}
  [data-theme="dark"] td {color:#263650!important}
  [data-theme="dark"] tbody tr:hover {background:#fff}
  [data-theme="dark"] .insight-list li {background:#f6f8fd!important;color:#43506a}
  [data-theme="dark"] .bar-name, [data-theme="dark"] .bar-value, [data-theme="dark"] .rec p, [data-theme="dark"] .detail {color:#35435b}
  [data-theme="dark"] .bar-track, [data-theme="dark"] .riskbar {background:#edf0f7!important}
  [data-theme="dark"] .bar-sub, [data-theme="dark"] .chart-caption {color:#73819b}
  [data-theme="dark"] .axis-label {fill:#8390aa}
  [data-theme="dark"] .grid-line {stroke:#e9edf5}
  [data-theme="dark"] .no-data, [data-theme="dark"] .method {background:#f6f8fc!important;border-color:#e6ebf2;color:#53627c}
  [data-theme="dark"] .callout {background:#eef8f6!important;border-color:#c8e8e0;color:#28675e}
  [data-theme="dark"] .rec {border-color:#ebeff6}
  [data-theme="dark"] .method label {color:#66738d}
  [data-theme="dark"] .ledger code {background:#f1f3f9;color:#6d7894}
  [data-theme="dark"] .pill-critical {background:#fee5e9;color:#a21c3a}
  [data-theme="dark"] .pill-high {background:#fff0df;color:#9d5d13}
  [data-theme="dark"] .pill-medium {background:#fff8df;color:#98731f}
  [data-theme="dark"] .pill-low {background:#e3f5ee;color:#167c64}
}
"""  # noqa: E501


def _h(value: Any) -> str:
    return escape(str(value if value is not None else "—"), quote=True)


def _num(value: Any, precision: int = 0) -> str:
    try:
        numeric = float(value)
        if not math.isfinite(numeric):
            return "—"
        return f"{numeric:,.{precision}f}"
    except (TypeError, ValueError):
        return "—"


def _f(value: Any) -> float:
    try:
        numeric = float(value)
        return numeric if math.isfinite(numeric) else 0.0
    except (TypeError, ValueError):
        return 0.0


def _money(value: Any, symbol: str = "$") -> str:
    numeric = _f(value)
    prefix = "−" if numeric < 0 else ""
    return f"{prefix}{_h(symbol)}{abs(numeric):,.2f}"


def _pct(value: Any) -> str:
    return f"{_f(value) * 100:.1f}%"


def _json(payload: dict[str, Any]) -> str:
    return (
        json.dumps(payload, ensure_ascii=False, default=str)
        .replace("<", "\\u003c")
        .replace(">", "\\u003e")
        .replace("&", "\\u0026")
    )


def _stats(values: list[tuple[str, str, str]]) -> str:
    return (
        '<div class="stat-grid">'
        + "".join(
            f'<div class="stat"><span class="label">{_h(name)}</span><strong class="value">{value}</strong><span class="hint">{_h(hint)}</span></div>'  # noqa: E501
            for name, value, hint in values
        )
        + "</div>"
    )


def _heading(title: str, note: str = "") -> str:
    return f'<div class="section-label"><h2>{_h(title)}</h2><span>{_h(note)}</span></div>'


def _card(title: str, subtitle: str, content: str, marker: str = "", classes: str = "") -> str:
    mark = f'<span class="mark">{_h(marker)}</span>' if marker else ""
    return (
        f'<section class="card pad {classes}"><header class="card-title">'
        f"<div><h3>{_h(title)}</h3><p>{_h(subtitle)}</p></div>{mark}</header>"
        f"{content}</section>"
    )


def _empty(message: str) -> str:
    return f'<div class="no-data">{_h(message)}</div>'


def _table(headings: list[str], rows: list[list[str]], minimum: str = "") -> str:
    if not rows:
        return _empty("No records available in this analysis.")
    th = "".join(f"<th scope='col'>{_h(value)}</th>" for value in headings)
    body = "".join("<tr>" + "".join(f"<td>{value}</td>" for value in row) + "</tr>" for row in rows)
    return f'<div class="table-scroll {minimum}"><table><thead><tr>{th}</tr></thead><tbody>{body}</tbody></table></div>'  # noqa: E501


def _line(
    rows: list[dict[str, Any]], xkey: str, ykey: str, symbol: str = "", currency: bool = False
) -> str:
    clean = [(str(r.get(xkey, "")), _f(r.get(ykey))) for r in rows[:36]]
    if not clean:
        return _empty("No time series is available for this dataset.")
    W, H, left, r, t, b = 780, 266, 65, 19, 25, 45
    values = [v for _, v in clean]
    low = min(0.0, min(values))
    high = max(values)
    if high == low:
        high = low + 1
    plotw, ploth = W - left - r, H - t - b

    def point(i: int, value: float) -> tuple[float, float]:
        return left + (plotw * i / max(len(clean) - 1, 1)), t + ploth * (high - value) / (
            high - low
        )  # noqa: E501

    coords = [point(i, value) for i, (_, value) in enumerate(clean)]
    poly = " ".join(f"{x:.1f},{y:.1f}" for x, y in coords)
    base_y = t + ploth
    fill_path = (
        f"M {coords[0][0]:.1f} {base_y:.1f} L "
        + " L ".join(f"{x:.1f} {y:.1f}" for x, y in coords)
        + f" L {coords[-1][0]:.1f} {base_y:.1f} Z"
    )
    guides = "".join(
        f'<line x1="{left}" y1="{t + ploth * i / 4:.1f}" x2="{W - r}" y2="{t + ploth * i / 4:.1f}" stroke="#e8edf5"/><text x="{left - 8}" y="{t + ploth * i / 4 + 4:.1f}" text-anchor="end" class="axis-label">{_h(_num(high - (high - low) * i / 4))}</text>'  # noqa: E501
        for i in range(5)
    )
    marks = "".join(
        f'<g><circle cx="{x:.1f}" cy="{y:.1f}" r="4.5" fill="#fff" stroke="#615ee9" stroke-width="3"/><title>{_h(date)}: {_money(value, symbol) if currency else _h(_num(value, 2))}</title></g>'  # noqa: E501
        for (date, value), (x, y) in zip(clean, coords, strict=True)
    )
    label_indices = sorted(
        set([0, len(clean) - 1, *range(0, len(clean), max(1, math.ceil(len(clean) / 6)))])
    )
    labels = "".join(
        f'<text x="{coords[i][0]:.1f}" y="{H - 18}" text-anchor="middle" class="axis-label">{_h(clean[i][0][:10])}</text>'  # noqa: E501
        for i in label_indices
    )
    return f'''<div class="chart-graphic"><svg viewBox="0 0 {W} {H}" role="img" aria-label="Time series line chart"><defs><linearGradient id="trend-fill" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#7367f6" stop-opacity=".22"/><stop offset="1" stop-color="#7367f6" stop-opacity="0"/></linearGradient></defs>{guides}<path d="{fill_path}" fill="url(#trend-fill)"/><polyline points="{poly}" fill="none" stroke="#645fee" stroke-width="3.3" stroke-linecap="round" stroke-linejoin="round"/>{marks}{labels}</svg><p class="chart-caption">Hover over a data point to see its underlying value. Trend is descriptive, not causal.</p></div>'''  # noqa: E501


def _bars(
    items: list[dict[str, Any]],
    label: str,
    amount: str,
    symbol: str = "",
    share: str = "",
    currency: bool = False,
    top: int = 8,
) -> str:
    selected = items[:top]
    if not selected:
        return _empty("No categorical breakdown is available for this dataset.")
    maximum = max([abs(_f(i.get(amount))) for i in selected] + [1.0])
    rows = []
    for item in selected:
        v = _f(item.get(amount))
        w = 100 * abs(v) / maximum
        note = (
            f"{_pct(item[share])} of total"
            if share and share in item
            else "Measured from source records"
        )
        display = _money(v, symbol) if currency else _h(_num(v, 0 if float(v).is_integer() else 2))
        rows.append(
            f'<div class="bar-row"><div class="bar-labels"><span class="bar-name" title="{_h(item.get(label))}">{_h(item.get(label))}</span><strong class="bar-value">{display}</strong></div><div class="bar-track"><div class="bar-fill" style="width:{w:.2f}%"></div></div><div class="bar-sub">{_h(note)}</div></div>'  # noqa: E501
        )
    return '<div class="bar-list">' + "".join(rows) + "</div>"


def _insights(items: Iterable[Any], empty: str = "No narrative insights were recorded.") -> str:
    entries = list(items)
    return (
        '<ul class="insight-list">'
        + "".join(f"<li>{_h(item)}</li>" for item in entries[:10])
        + "</ul>"
        if entries
        else _empty(empty)
    )


def _anomalies(items: list[dict[str, Any]], symbol: str = "$") -> str:
    rows: list[list[str]] = []
    for item in items[:30]:
        level = str(item.get("severity", "medium")).lower()
        safe_level = level if level in {"critical", "high", "medium", "low"} else "neutral"
        score = _f(item.get("risk_score"))
        rows.append(
            [
                f'<strong>{_h(item.get("supplier", "Unknown"))}</strong><div class="data-signal">{_h(item.get("category", ""))}</div>',  # noqa: E501
                _money(item.get("amount"), symbol),
                f'<span class="pill pill-{safe_level}">{_h(level)}</span><div class="riskbar"><span style="width:{max(0, min(100, score)):.0f}%"></span></div>',  # noqa: E501
                _h(item.get("reason", "Review required")),
            ]
        )
    return (
        '<div data-anomaly-queue><div class="data-signal" data-severity-filter="all" data-anomaly-search>Full anomaly review · source risk scores</div>'  # noqa: E501
        + _table(["Supplier / category", "Amount", "Risk", "Evidence"], rows)
        + "</div>"
    )


def _forecast(forecast: dict[str, Any], symbol: str) -> str:
    entries = forecast.get("forecast") or []
    if not entries:
        return _empty("At least three observed periods are required before forecasting.")
    rows = [
        [
            _h(r.get("month")),
            _money(r.get("predicted_spend"), symbol),
            _money(r.get("lower_bound"), symbol),
            _money(r.get("upper_bound"), symbol),
        ]
        for r in entries
    ]
    return (
        _line(entries, "month", "predicted_spend", symbol, True)
        + _table(["Period", "Baseline", "Low", "High"], rows, "compact")
        + '<p class="chart-caption">Heuristic baseline and uncertainty bounds; not a calibrated confidence interval.</p>'  # noqa: E501
    )


def _risks(items: list[dict[str, Any]], symbol: str) -> str:
    rows = []
    for x in items[:15]:
        score = _f(x.get("risk_score"))
        level = str(x.get("risk_level", "medium")).lower()
        safe_level = level if level in {"critical", "high", "medium", "low"} else "neutral"
        rows.append(
            [
                f"<strong>{_h(x.get('supplier'))}</strong>",
                f'{_num(score)}<div class="riskbar"><span style="width:{max(0, min(100, score)):.0f}%"></span></div>',  # noqa: E501
                f'<span class="pill pill-{safe_level}">{_h(level)}</span>',
                _money(x.get("spend"), symbol),
                _money(x.get("anomaly_exposure"), symbol),
            ]
        )
    return _table(["Supplier", "Risk /100", "Level", "Spend", "Flagged exposure"], rows)


def _quality(schema: dict[str, Any] | None, quality: dict[str, Any] | None) -> str:
    schema = schema or {}
    quality = quality or {}
    pairs = [
        ("Rows profiled", schema.get("row_count", "—")),
        ("Columns profiled", schema.get("column_count", "—")),
        ("Missing cells", quality.get("missing_cells", "—")),
        ("Exact duplicate rows", quality.get("duplicate_row_count", "—")),
    ]
    return (
        '<div class="method-grid">'
        + "".join(
            f'<div class="method"><label>{_h(k)}</label><strong>{_h(v)}</strong></div>'
            for k, v in pairs
        )
        + "</div>"
    )


def _recommendations(items: list[Any]) -> str:
    if not items:
        return _empty("No additional recommendations were recorded.")
    return (
        '<div class="recommendations">'
        + "".join(
            f'<div class="rec"><span class="rec-n">{i + 1:02}</span><p>{_h(item)}</p></div>'
            for i, item in enumerate(items[:12])
        )
        + "</div>"
    )


def _source_ids(ids: list[str]) -> str:
    return (
        '<div class="ledger">' + "".join(f"<code>{_h(x)}</code>" for x in ids[:25]) + "</div>"
        if ids
        else _empty("No lineage references provided.")
    )


def _nav(mode: str, generic: bool) -> str:
    choices = [
        ("overview", "Overview"),
        ("findings", "Key findings"),
        ("performance", "Performance"),
        ("risks", "Risk & anomalies" if not generic else "Outlier review"),
        ("recommendations", "Recommendations"),
        ("methodology", "Data & methodology"),
    ]
    if mode == "chart":
        choices = [
            ("overview", "Chart overview"),
            ("performance", "Visual evidence"),
            ("methodology", "Source information"),
        ]
    return "".join(f'<a href="#{key}">{name}</a>' for key, name in choices)


def _shell(
    title: str,
    intro: str,
    eyebrow: str,
    content: str,
    nav: str,
    source_id: str = "",
    role: str = "report",
    meta: list[str] | None = None,
    json_payload: dict[str, Any] | None = None,
    json_role: str = "",
) -> str:
    spans = "".join(f"<span>{_h(x)}</span>" for x in (meta or []))
    embedded = (
        f'<script type="application/json" data-role="{_h(json_role)}">{_json(json_payload)}</script>'  # noqa: E501
        if json_payload is not None and json_role
        else ""
    )
    return f'''<!doctype html><html lang="en" data-theme="dark"><head><meta charset="utf-8"/><meta name="viewport" content="width=device-width, initial-scale=1"/><meta name="color-scheme" content="dark light"/><title>{_h(title)} · Enterprise AI OS</title><style>{CSS}{DARK_CSS}</style></head><body><div class="shell"><aside class="rail" aria-label="Document navigation"><div class="brand"><div class="brand-mark">✦</div><div>ENTERPRISE<br/>INTELLIGENCE</div></div><div><p class="rail-label">REPORT SECTIONS</p><nav>{nav}</nav></div><div class="rail-tip"><strong>Evidence-led analysis</strong>All figures come from the saved workflow output. Rule-based flags are not conclusions of wrongdoing.</div></aside><div class="work"><div class="content"><div class="topbar"><div class="topbar-path">Workspace / Intelligence / <b>{_h(role.title())}</b></div><div class="topbar-actions"><span class="tiny-tag">Generated from saved analysis</span><span class="print-link">Save as PDF: ⌘P / Ctrl+P</span></div></div><main data-source-artifact-id="{_h(source_id)}" class="{_h(role)}"><header id="overview" class="hero section-anchor"><span class="eyebrow">{_h(eyebrow)}</span><h1>{_h(title)}</h1><p>{_h(intro)}</p><div class="hero-meta">{spans}</div></header>{content}</main><footer class="footer"><span>ENTERPRISE AI OS · Decision support, not automated financial advice</span><span>Source-linked · Offline-ready · Print-friendly</span></footer></div></div></div>{embedded}</body></html>'''  # noqa: E501


def _chart_body(chart: ProcurementChartSpec, currency_symbol: str = "$") -> str:
    slug = chart.slug
    data = chart.data
    if slug in ("supplier-spend", "category-breakdown"):
        return _bars(
            data,
            "supplier" if slug == "supplier-spend" else "category",
            "spend",
            currency_symbol,
            "share",
            True,
        )
    if slug == "monthly-trend":
        return _line(data, "month", "spend", currency_symbol, True)
    if slug == "time-trend":
        return _line(data, "period", "value")
    if slug == "anomaly-review":
        return _anomalies(data, currency_symbol)
    if slug == "supplier-risk":
        return _risks(data, currency_symbol)
    if slug == "spend-forecast":
        return _forecast({"forecast": data}, currency_symbol)
    if slug == "segment-profile":
        return _bars(data, "value", "count", share="share")
    if slug == "measure-summary":
        return _table(
            ["Measure", "Count", "Mean", "Minimum", "Maximum"],
            [
                [
                    _h(d.get("column")),
                    _h(d.get("count")),
                    _num(d.get("mean"), 2),
                    _num(d.get("min"), 2),
                    _num(d.get("max"), 2),
                ]
                for d in data
            ],
        )
    if slug == "outlier-review":
        return _table(
            ["Measure", "Flagged", "Lower", "Upper"],
            [
                [
                    _h(d.get("column")),
                    _h(d.get("outlier_count")),
                    _h(_num(d.get("lower"), 2)),
                    _h(_num(d.get("upper"), 2)),
                ]
                for d in data
            ],
        )
    if slug == "semantic-roles":
        return _table(
            ["Role", "Columns"],
            [[_h(d.get("role")), _h(", ".join(d.get("columns") or []))] for d in data],
        )
    if slug in ("dataset-overview", "kpi-summary"):
        return _stats(
            [
                (
                    _h(d.get("metric", "Metric")).replace("_", " ").title(),
                    _h(_num(d.get("value"), 2))
                    if isinstance(d.get("value"), float)
                    else _h(d.get("value")),
                    "Based on saved analysis",
                )
                for d in data[:8]
            ]
        )
    return chart.body_html


def render_premium_chart_document(
    chart: ProcurementChartSpec,
    source_artifact_id: str,
    eyebrow: str = "Dataset intelligence chart",
) -> str:
    graphical = _chart_body(chart, chart.currency_symbol)
    contents = _heading("Visual evidence", "Verified artifact") + _card(
        chart.title, chart.description, graphical, chart.chart_type, "chart-full"
    )
    contents += _heading("Source information") + _card(
        "Artifact provenance", "Reproducibility and traceability", _source_ids([source_artifact_id])
    )
    return _shell(
        chart.title,
        chart.description,
        eyebrow,
        contents,
        _nav("chart", False),
        source_artifact_id,
        role="chart-page",
        meta=[chart.chart_type.title(), "Data points: " + str(len(chart.data))],
        json_payload={"source_artifact_id": source_artifact_id, "data": chart.data},
        json_role="chart-data",
    )


def _procurement_sections(analysis: dict[str, Any], mode: str) -> str:
    kpis = analysis.get("kpis") or {}
    dataset = analysis.get("dataset") or {}
    symbol = str(dataset.get("currency_symbol") or "$")
    sections = _heading("Performance at a glance", "Calculated from transaction data")
    sections += _stats(
        [
            (
                "Total spend",
                _money(kpis.get("total_spend"), symbol),
                "Total analyzed transaction value",
            ),
            ("Transactions", _h(_num(dataset.get("row_count"))), "Source records"),
            (
                "Flagged transactions",
                _h(_num(kpis.get("anomaly_count", 0))),
                "Investigate; not confirmed fraud",
            ),
            (
                "Savings opportunities",
                _money(kpis.get("estimated_savings"), symbol),
                "Heuristic estimate; not realized",
            ),
            ("Suppliers", _h(_num(kpis.get("supplier_count"))), "Unique supplier groups"),
            ("Categories", _h(_num(kpis.get("category_count"))), "Procurement categories"),
            ("Risk exposure", _money(kpis.get("risk_exposure"), symbol), "Sum of flagged amounts"),
            (
                "At-risk suppliers",
                _h(_num(kpis.get("at_risk_supplier_count"))),
                "Heuristic risk profiles",
            ),
        ]
    )
    sections += '<div id="findings" class="section-anchor">' + _heading(
        "Executive Insights", "Source-derived signals"
    )
    sections += (
        _card(
            "What the data tells us",
            "Deterministic observations and cautious interpretation",
            _insights(analysis.get("insights") or []),
            "ANALYSIS",
        )
        + "</div>"
    )
    sections += '<div id="performance" class="section-anchor">' + _heading(
        "Spend & concentration", "Historical, not forecast"
    )
    sections += '<div class="two">' + _card(
        "Monthly spend trend",
        "Transaction totals by month",
        _line(analysis.get("spend_trend") or [], "month", "spend", symbol, True),
        "TIME SERIES",
    )
    sections += (
        _card(
            "Top suppliers",
            "Supplier share of analyzed spend",
            _bars(
                analysis.get("spend_by_supplier") or [], "supplier", "spend", symbol, "share", True
            ),
            "CONCENTRATION",
        )
        + "</div>"
    )
    sections += '<div class="two section-card">' + _card(
        "Spend by category",
        "Observed category totals",
        _bars(analysis.get("spend_by_category") or [], "category", "spend", symbol, "share", True),
        "ALLOCATION",
    )
    sections += (
        _card(
            "Spend forecast",
            "Simple linear baseline; uncertainty is heuristic",
            _forecast(analysis.get("spend_forecast") or {}, symbol),
            "PROJECTION",
        )
        + "</div></div>"
    )
    sections += '<div id="risks" class="section-anchor">' + _heading(
        "Risk & exception review", "Explainable, rule-based signals"
    )
    sections += _card(
        "Flagged transactions",
        "A review queue, not a determination of fraud",
        _anomalies(analysis.get("anomalies") or [], symbol),
        "INVESTIGATE",
    )
    sections += (
        '<div class="section-card">'
        + _card(
            "Supplier risk profiles",
            "Heuristic supplier concentration and anomaly exposure",
            _risks(analysis.get("supplier_risk_profiles") or [], symbol),
            "SUPPLIER RISK",
        )
        + "</div></div>"
    )
    opportunities = analysis.get("savings_opportunities") or []
    items = [
        (
            f"{item.get('rationale') or item.get('description') or item.get('opportunity') or 'Review savings opportunity'} "  # noqa: E501
            f"Estimated opportunity: {symbol}{_num(item.get('estimated_savings', item.get('savings', 0)), 2)} "  # noqa: E501
            "(heuristic; not realized)."
        )
        if isinstance(item, dict)
        else str(item)
        for item in opportunities
    ]
    sections += '<div id="recommendations" class="section-anchor">' + _heading(
        "Recommended next actions", "Human review required"
    )
    sections += (
        _card(
            "Action plan",
            "Prioritized source-derived opportunities",
            _recommendations(
                items
                or [
                    "Review the flagged transactions against original invoices and procurement policy.",  # noqa: E501
                    "Validate supplier concentration and savings assumptions before acting.",
                ]
            ),
        )
        + "</div>"
    )
    return sections


def _generic_sections(analysis: dict[str, Any], mode: str) -> str:
    kpis, plan = analysis.get("kpis") or {}, analysis.get("analysis_plan") or {}
    sections = _heading("Dataset health", "Recorded profile metrics")
    sections += _stats(
        [
            ("Rows", _h(_num(kpis.get("row_count"))), "Observed records"),
            ("Columns", _h(_num(kpis.get("column_count"))), "Available fields"),
            ("Completeness", _pct(kpis.get("completeness")), "Non-missing cell ratio"),
            ("Outlier values", _h(_num(kpis.get("outlier_count"))), "Rule-based IQR signals"),
            ("Measures", _h(_num(kpis.get("measure_count"))), "Inferred quantitative fields"),
            ("Dimensions", _h(_num(kpis.get("dimension_count"))), "Inferred categorical fields"),
            ("Duplicate rows", _h(_num(kpis.get("duplicate_row_count"))), "Exact full-row matches"),
            ("Analysis plan", _h(plan.get("recipe", "generic")).title(), "Schema-inferred recipe"),
        ]
    )
    sections += '<div id="findings" class="section-anchor">' + _heading(
        "Key Findings", "Deterministic dataset analysis"
    )
    sections += (
        _card(
            "Observations",
            "Findings from the analyzed data",
            _insights(analysis.get("insights") or []),
        )
        + "</div>"
    )
    measures, dimensions, trend = (
        analysis.get("measure_summaries") or [],
        analysis.get("dimension_summaries") or [],
        analysis.get("time_series") or [],
    )
    sections += '<div id="performance" class="section-anchor">' + _heading(
        "Performance & structure", "Observed value distribution"
    )
    sections += '<div class="two">' + _card(
        "Primary time trend",
        "Monthly sums of the selected measure or record count",
        _line(trend, "period", "value"),
        "TREND",
    )
    sections += (
        _card(
            "Top categories",
            "Record-count distribution for the first inferred dimension",
            _bars(
                (dimensions[0].get("top_values") or []) if dimensions else [],
                "value",
                "count",
                share="share",
            ),
            "DISTRIBUTION",
        )
        + "</div>"
    )
    sections += (
        '<div class="section-card">'
        + _card(
            "Numeric measures",
            "Observed summary statistics",
            _table(
                ["Measure", "Count", "Total", "Mean", "Min", "Max"],
                [
                    [
                        _h(m.get("column")),
                        _h(m.get("count")),
                        _h(_num(m.get("sum"), 2)),
                        _h(_num(m.get("mean"), 2)),
                        _h(_num(m.get("min"), 2)),
                        _h(_num(m.get("max"), 2)),
                    ]
                    for m in measures
                ],
            ),
            "STATISTICS",
        )
        + "</div></div>"
    )
    sections += '<div id="risks" class="section-anchor">' + _heading(
        "Outliers & quality", "Descriptive checks only"
    )
    sections += (
        _card(
            "Numeric outlier review",
            "IQR bounds and counts by field",
            _table(
                ["Measure", "Outliers", "Lower bound", "Upper bound"],
                [
                    [
                        _h(o.get("column")),
                        _h(o.get("outlier_count")),
                        _h(_num(o.get("lower"), 2)),
                        _h(_num(o.get("upper"), 2)),
                    ]
                    for o in (analysis.get("outliers") or [])
                ],
            ),
            "ANALYTICS",
        )
        + "</div>"
    )
    sections += '<div id="recommendations" class="section-anchor">' + _heading(
        "Recommended next actions", "Based on data profile"
    )
    sections += (
        _card(
            "Analysis recommendations",
            "Validate inferred roles and material outliers",
            _recommendations(analysis.get("recommendations") or []),
        )
        + "</div>"
    )
    return sections


def render_premium_dashboard_document(
    analysis: dict[str, Any],
    charts: list[ProcurementChartSpec],
    source_artifact_id: str,
    chart_artifact_ids: list[str] | None = None,
) -> str:
    generic = analysis.get("analysis_type") == "generic"
    title = "Dataset Intelligence Dashboard" if generic else "Procurement Dashboard"
    intro = "An evidence-led overview of detected patterns, quality signals, and generated business intelligence."  # noqa: E501
    sections = (
        _generic_sections(analysis, "dashboard")
        if generic
        else _procurement_sections(analysis, "dashboard")
    )
    # Preserve the chart index, including chart titles, to make saved artifacts discoverable.
    tiles = "".join(
        f'<div class="method"><label>{_h(c.chart_type).upper()}</label><strong>{_h(c.title)}</strong></div>'  # noqa: E501
        for c in charts
    )
    sections += (
        _heading("Chart library", "Individually downloadable artifacts")
        + '<div class="method-grid">'
        + tiles
        + "</div>"
    )
    sections += (
        '<div id="methodology" class="section-anchor">'
        + _heading("Data & methodology", "Provenance and caveats")
        + _card(
            "Source lineage",
            "Saved analysis and chart artifact identifiers",
            _source_ids([source_artifact_id] + list(chart_artifact_ids or [])),
        )
        + "</div>"
    )
    return _shell(
        title,
        intro,
        "Dynamic dataset intelligence" if generic else "Executive procurement intelligence",
        sections,
        _nav("dashboard", generic),
        source_artifact_id,
        role="dashboard",
        meta=["Executive Insights", "Deterministic analytics", "Source-linked charts"],
        json_payload={
            "source_artifact_id": source_artifact_id,
            "chart_artifact_ids": list(chart_artifact_ids or []),
            "analysis": analysis,
        },
        json_role="dashboard-data",
    )


def render_premium_report_document(
    analysis: dict[str, Any],
    source_artifact_ids: list[str],
    schema_profile: dict[str, Any] | None = None,
    quality_report: dict[str, Any] | None = None,
) -> str:
    generic = analysis.get("analysis_type") == "generic"
    title = "Exploratory Dataset Analysis Report" if generic else "Procurement Analysis Report"
    intro = (
        "A structured decision brief covering dataset characteristics, descriptive performance, anomalies, and recommendations."  # noqa: E501
        if generic
        else "Executive decision brief covering expenditure, supplier concentration, flagged risks, savings opportunities, and evidence-backed recommendations."  # noqa: E501
    )
    contents = (
        _generic_sections(analysis, "report")
        if generic
        else _procurement_sections(analysis, "report")
    )
    plan = analysis.get("analysis_plan") or {}
    quality_block = _quality(schema_profile, quality_report)
    if generic:
        role_pairs = [
            ("Measures", plan.get("measures") or []),
            ("Dimensions", plan.get("dimensions") or []),
            ("Time", plan.get("time_columns") or []),
            ("Identifiers", plan.get("identifiers") or []),
        ]
        role_table = _table(
            ["Role", "Fields"],
            [[_h(k), _h(", ".join(map(str, v)) or "None")] for k, v in role_pairs],
            "compact",
        )
        quality_block += '<div style="margin-top:18px">' + role_table + "</div>"
    limitations = (
        (analysis.get("limitations") or [])
        if generic
        else [
            "Anomaly scores prioritize review and do not establish fraud.",
            "Savings estimates are heuristic, not realized savings.",
            "Forecast ranges are heuristic bounds, not statistically calibrated confidence intervals.",  # noqa: E501
            "Mixed currency data is not converted using live foreign-exchange rates.",
        ]
    )
    contents += '<div id="methodology" class="section-anchor">' + _heading(
        "Quality, methodology & audit trail", "Read before decisions"
    )
    contents += '<div class="two">' + _card(
        "Dataset quality",
        "Missing values and exact duplicate checks",
        quality_block,
        "DATA QUALITY",
    )
    contents += (
        _card(
            "Limitations & interpretation",
            "Boundaries of the deterministic analysis",
            _insights(limitations),
            "METHOD",
        )
        + "</div>"
    )
    contents += (
        '<div class="section-card">'
        + _card(
            "Artifact lineage",
            "Identifiers of the outputs used to assemble this report",
            _source_ids(source_artifact_ids),
            "PROVENANCE",
        )
        + "</div></div>"
    )
    return _shell(
        title,
        intro,
        "Management intelligence / Executive report",
        contents,
        _nav("report", generic),
        source_artifact_ids[0] if source_artifact_ids else "",
        role="report",
        meta=["HTML executive edition", "Print-ready layout", "Source-traceable evidence"],
    )
