"""Self-contained HTML report for a run (D-020).

One file, no internet needed: styles inline, screenshots embedded as base64.
Everything that comes from a test file, a web page or an LLM is HTML-escaped.
"""

from __future__ import annotations

import base64
from html import escape
from pathlib import Path

from .runner import RunReport, StepResult

STATUS = {  # status -> (label, css class)
    "ok": ("Passed", "ok"),
    "resolved": ("Found", "found"),
    "healed": ("Healed", "healed"),
    "failed": ("Failed", "failed"),
}

CSS = """
:root { --bg:#f6f7f9; --card:#fff; --ink:#1d2330; --muted:#6b7280; --line:#e5e7eb;
  --ok:#15803d; --ok-bg:#dcfce7; --found:#1d4ed8; --found-bg:#dbeafe;
  --healed:#c2410c; --healed-bg:#ffedd5; --failed:#b91c1c; --failed-bg:#fee2e2; }
* { box-sizing: border-box; }
body { margin:0; background:var(--bg); color:var(--ink);
  font:15px/1.5 -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif; }
.wrap { max-width: 980px; margin: 0 auto; padding: 32px 20px 48px; }
header { display:flex; align-items:flex-start; justify-content:space-between; gap:16px; flex-wrap:wrap; }
.brand { font-size:13px; font-weight:600; letter-spacing:.08em; text-transform:uppercase; color:var(--muted); }
h1 { margin:4px 0 6px; font-size:26px; }
.meta { color:var(--muted); font-size:13px; display:flex; gap:14px; flex-wrap:wrap; }
.verdict { font-size:15px; font-weight:700; padding:8px 18px; border-radius:999px; }
.verdict.pass { background:var(--ok-bg); color:var(--ok); }
.verdict.fail { background:var(--failed-bg); color:var(--failed); }
.tiles { display:grid; grid-template-columns:repeat(auto-fit, minmax(120px, 1fr)); gap:12px; margin:24px 0 28px; }
.tile { background:var(--card); border:1px solid var(--line); border-radius:12px; padding:14px 16px; }
.tile b { display:block; font-size:26px; line-height:1.1; }
.tile span { color:var(--muted); font-size:13px; }
.tile.healed b { color:var(--healed); } .tile.found b { color:var(--found); } .tile.failed b { color:var(--failed); }
.step { background:var(--card); border:1px solid var(--line); border-radius:12px; padding:16px 18px;
  margin-bottom:12px; display:grid; grid-template-columns: 32px 1fr auto; gap:14px; align-items:start; }
.step.healed { border-left:4px solid var(--healed); } .step.failed { border-left:4px solid var(--failed); }
.step.found { border-left:4px solid var(--found); }
.num { width:28px; height:28px; border-radius:50%; background:var(--bg); display:grid; place-items:center;
  font-weight:600; font-size:13px; color:var(--muted); }
.title { display:flex; gap:10px; align-items:center; flex-wrap:wrap; }
.action { font:12px/1 ui-monospace, SFMono-Regular, Menlo, monospace; background:var(--bg); border:1px solid var(--line);
  padding:4px 7px; border-radius:6px; color:var(--muted); }
.intent { font-weight:600; }
.chip { font-size:12px; font-weight:700; padding:3px 10px; border-radius:999px; }
.chip.ok { background:var(--ok-bg); color:var(--ok); } .chip.found { background:var(--found-bg); color:var(--found); }
.chip.healed { background:var(--healed-bg); color:var(--healed); } .chip.failed { background:var(--failed-bg); color:var(--failed); }
.sel { margin-top:10px; font-size:13px; display:grid; grid-template-columns: 44px 1fr; gap:4px 8px; }
.sel .k { color:var(--muted); }
code { font:12.5px/1.4 ui-monospace, SFMono-Regular, Menlo, monospace; word-break:break-all; }
.was code { color:var(--failed); text-decoration:line-through; } .now code { color:var(--ok); }
.how { margin-top:10px; font-size:13px; color:var(--muted); display:flex; gap:10px; align-items:center; flex-wrap:wrap; }
.by { font-weight:700; color:var(--ink); }
.meter { width:110px; height:8px; border-radius:4px; background:var(--line); overflow:hidden; display:inline-block; vertical-align:middle; }
.meter i { display:block; height:100%; background:var(--ok); }
.meter.low i { background:#d97706; }
.error { margin-top:10px; background:var(--failed-bg); color:var(--failed); border-radius:8px; padding:8px 10px; font-size:13px; }
.shot img { max-width:260px; max-height:170px; border:1px solid var(--line); border-radius:8px; display:block; cursor:zoom-in; }
.shot.wide { display:block; margin-top:12px; }
.shot.wide img { max-width:100%; max-height:none; }
footer { margin-top:28px; color:var(--muted); font-size:12px; text-align:center; }
@media (max-width: 680px) { .step { grid-template-columns: 28px 1fr; } .shot { grid-column: 2; } }
"""


def _img(png: bytes | None, wide: bool = False) -> str:
    if not png:
        return ""
    data = base64.b64encode(png).decode()
    cls = "shot wide" if wide else "shot"
    return (f'<a class="{cls}" href="data:image/png;base64,{data}" target="_blank">'
            f'<img alt="screenshot" src="data:image/png;base64,{data}"></a>')


def _step(s: StepResult) -> str:
    label, cls = STATUS.get(s.status, (s.status, "ok"))
    parts = [
        f'<div class="step {cls}"><div class="num">{s.index + 1}</div><div>',
        f'<div class="title"><span class="action">{escape(s.action)}</span>'
        f'<span class="intent">{escape(s.intent)}</span><span class="chip {cls}">{label}</span></div>',
    ]
    if s.status in ("healed", "resolved"):
        rows = ""
        if s.old_selector:
            rows += f'<span class="k">was</span><span class="was"><code>{escape(s.old_selector)}</code></span>'
        rows += f'<span class="k">{"now" if s.old_selector else "found"}</span>' \
                f'<span class="now"><code>{escape(s.selector or "")}</code></span>'
        parts.append(f'<div class="sel">{rows}</div>')
        conf = max(0.0, min(1.0, s.confidence or 0.0))
        by = "AI (LLM)" if s.method == "llm" else "Heuristic (free)"
        parts.append(
            f'<div class="how"><span>by <span class="by">{by}</span></span>'
            f'<span class="meter{" low" if conf < 0.7 else ""}" title="confidence"><i style="width:{conf * 100:.0f}%"></i></span>'
            f'<span>{conf:.0%} confident</span>'
            + (f'<span>· {escape(s.reason)}</span>' if s.reason else "") + "</div>")
    if s.error:
        parts.append(f'<div class="error">{escape(s.error)}</div>')
    if s.status == "failed":  # whole page, shown large under the error
        parts.append(_img(s.screenshot, wide=True))
        parts.append("</div><div></div></div>")
    else:
        parts.append("</div>")
        parts.append(_img(s.screenshot) or "<div></div>")
        parts.append("</div>")
    return "".join(parts)


def render_html(r: RunReport) -> str:
    counts = {k: sum(1 for s in r.steps if s.status == k) for k in STATUS}
    verdict = '<span class="verdict pass">PASSED</span>' if r.passed else '<span class="verdict fail">FAILED</span>'
    meta = [r.started_at, f"{r.duration_s}s", f"AI: {r.llm}" if r.llm else "AI: off (heuristic only)"]
    if r.base_url:
        meta.append(r.base_url)
    tiles = "".join(
        f'<div class="tile {cls}"><b>{n}</b><span>{label}</span></div>'
        for n, label, cls in [
            (len(r.steps), "Steps run", ""), (counts["ok"], "Passed as-is", ""),
            (counts["resolved"], "Found (first run)", "found"), (counts["healed"], "Healed", "healed"),
            (counts["failed"], "Failed", "failed"),
        ])
    return f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Healwright report: {escape(r.test)}</title><style>{CSS}</style></head>
<body><div class="wrap">
<header><div><div class="brand">Healwright report</div><h1>{escape(r.test)}</h1>
<div class="meta">{"".join(f"<span>{escape(m)}</span>" for m in meta if m)}</div></div>{verdict}</header>
<div class="tiles">{tiles}</div>
{"".join(_step(s) for s in r.steps)}
<footer>Generated by Healwright. Healed selectors are saved to the test only with <code>--update</code> on a passing run.</footer>
</div></body></html>
"""


def write_html(r: RunReport, path: str | Path) -> None:
    Path(path).write_text(render_html(r), encoding="utf-8")
