"""Render the self-contained static status page.

The page is one ``index.html`` with inline CSS and JS (no external scripts
or stylesheets), plus a copy of ``summary.json`` that the page polls for
live updates. Images (logo, favicon) are the only external resources, and
only when the config points at them.
"""

from __future__ import annotations

import json
import shutil
from datetime import datetime, timezone
from html import escape
from pathlib import Path
from urllib.parse import urlparse
from xml.sax.saxutils import escape as xml_escape

from . import __version__, legal as legal_texts, stats
from .incidents import duration

GITHUP_URL = "https://github.com/StuxGroup/GitHup"
SERVICES_URL = "https://services.stux.group"
CHANGELOGS_URL = "https://githup.stux.group/changelogs/#githup"
# The GitHup mark (assets/icon.svg), inlined so the page stays self-contained.
GITHUP_ICON = ('<svg class="gh-mark" viewBox="0 0 64 64" aria-hidden="true" focusable="false">'
               '<defs><linearGradient id="gh-g" x1="0" y1="0" x2="1" y2="1">'
               '<stop offset="0" stop-color="#b06bff"/><stop offset="1" stop-color="#3ba7ff"/></linearGradient></defs>'
               '<rect width="64" height="64" rx="14" fill="url(#gh-g)"/>'
               '<path d="M9 38h10l5-10 7 18 7-24 5 16h4l8-12M47 22h9v9" fill="none" stroke="#fff" '
               'stroke-width="5" stroke-linecap="round" stroke-linejoin="round"/></svg>')
GITHUP_FAVICON = "data:image/svg+xml," + (GITHUP_ICON.replace(' class="gh-mark"', ' xmlns="http://www.w3.org/2000/svg"')
                                          .replace(' aria-hidden="true" focusable="false"', "")
                                          .replace("#", "%23").replace('"', "'"))
HISTORY_DAYS = 90
SPARK_HOURS = 48

# The shared Stux site banner (dev / coming soon / maintenance / notice), copied verbatim from
# Stux.Dev Labs and inlined into the page like the rest of its CSS and JS.
_BANNER_DIR = Path(__file__).resolve().parent / "banner"
BANNER_CSS = (_BANNER_DIR / "site-banner.css").read_text(encoding="utf-8")
BANNER_JS = (_BANNER_DIR / "site-banner.js").read_text(encoding="utf-8")


# --------------------------------------------------------------------------
# colour helpers


def _rgb(hex_: str) -> tuple[int, int, int]:
    h = hex_.lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def _hex(rgb) -> str:
    return "#" + "".join(f"{max(0, min(255, round(c))):02x}" for c in rgb)


def _luminance(hex_: str) -> float:
    def ch(c):
        c /= 255
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    r, g, b = (ch(c) for c in _rgb(hex_))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast(a: str, b: str) -> float:
    la, lb = sorted((_luminance(a), _luminance(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


def _mix(a: str, b: str, t: float) -> str:
    ra, rb = _rgb(a), _rgb(b)
    return _hex(x + (y - x) * t for x, y in zip(ra, rb))


def readable(accent: str, background: str, ratio: float = 4.5) -> str:
    """Nudge ``accent`` towards black or white until it reads on ``background``."""
    target = "#000000" if _luminance(background) > 0.5 else "#ffffff"
    colour = accent
    t = 0.0
    while contrast(colour, background) < ratio and t < 1:
        t = round(t + 0.05, 2)
        colour = _mix(accent, target, t)
    return colour


def on_colour(background: str) -> str:
    return "#ffffff" if contrast("#ffffff", background) >= contrast("#111111", background) else "#111111"


# --------------------------------------------------------------------------
# formatting


def _utc(ts: int | None) -> str:
    if not ts:
        return "never"
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


def _iso(ts: int | None) -> str:
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ") if ts else ""


def _time(ts: int | None, field: str = "") -> str:
    if not ts:
        return '<time data-ts="">never</time>'
    f = f' data-field="{field}"' if field else ""
    return f'<time datetime="{_iso(ts)}" data-ts="{ts}"{f}>{_utc(ts)}</time>'


def _date_label(iso_day: str) -> str:
    d = datetime.strptime(iso_day, "%Y-%m-%d")
    return d.strftime("%a %d %b %Y")


def _ms(v: int | None) -> str:
    return "n/a" if v is None else f"{v:,} ms"


LEVEL_TEXT = {
    "ok": "Operational",
    "degraded": "Slow responses",
    "minor": "Some downtime",
    "major": "Major outage",
    "none": "No data",
}
STATUS_ICON = {"up": "✔", "degraded": "▲", "down": "✖", "partial": "▲", "unknown": "•"}
GROUP_TEXT = {"up": "Operational", "degraded": "Degraded", "partial": "Partial outage", "down": "Down", "unknown": "No data"}


# --------------------------------------------------------------------------
# pieces


def _bars(monitor_name: str, days: list[dict]) -> str:
    items = []
    last = len(days) - 1
    for i, d in enumerate(days):
        label = _date_label(d["date"])
        if d["checks"]:
            detail = f"{stats.fmt_pct(d['uptime'])} uptime · {d['checks']} checks"
            if d["down"]:
                detail += f" · {d['down']} down"
            if d["degraded"]:
                detail += f" · {d['degraded']} slow"
            if d["avg_ms"] is not None:
                detail += f" · avg {d['avg_ms']} ms"
        else:
            detail = "No data"
        tip = f"{label} (UTC)\n{LEVEL_TEXT[d['level']]}\n{detail}"
        sr = f"{label}: {LEVEL_TEXT[d['level']]}, {detail}"
        items.append(
            f'<li class="bar lvl-{d["level"]}" tabindex="{0 if i == last else -1}" '
            f'data-tip="{escape(tip)}"><span class="sr-only">{escape(sr)}</span></li>'
        )
    return (f'<ol class="bars" aria-label="{escape(monitor_name)}: daily history for the last {len(days)} days. '
            f'Use the arrow keys to move between days.">' + "".join(items) + "</ol>")


def _spark(monitor_name: str, series: list[int | None]) -> str:
    values = [v for v in series if v is not None]
    if len(values) < 2:
        return '<p class="spark-empty">Not enough data for a response-time chart yet.</p>'
    w, h, pad = 240, 44, 3
    hi = max(values)
    lo = min(values)
    span = max(hi - lo, 1)
    step = w / (len(series) - 1)
    segments: list[list[tuple[float, float]]] = [[]]
    for i, v in enumerate(series):
        if v is None:
            if segments[-1]:
                segments.append([])
            continue
        y = pad + (h - 2 * pad) * (1 - (v - lo) / span)
        segments[-1].append((round(i * step, 1), round(y, 1)))
    lines, areas = [], []
    for seg in segments:
        if not seg:
            continue
        if len(seg) == 1:
            x, y = seg[0]
            lines.append(f'<circle cx="{x}" cy="{y}" r="1.6" class="spark-dot"/>')
            continue
        pts = " ".join(f"{x},{y}" for x, y in seg)
        lines.append(f'<polyline points="{pts}" class="spark-line"/>')
        areas.append(f'<polygon points="{seg[0][0]},{h} {pts} {seg[-1][0]},{h}" class="spark-area"/>')
    avg = round(sum(values) / len(values))
    label = (f"{monitor_name}: response time over the last {SPARK_HOURS} hours. "
             f"Average {avg} ms, fastest {lo} ms, slowest {hi} ms.")
    return (
        f'<figure class="spark"><svg viewBox="0 0 {w} {h}" preserveAspectRatio="none" role="img" '
        f'aria-label="{escape(label)}"><title>{escape(label)}</title>{"".join(areas)}{"".join(lines)}</svg>'
        f'<figcaption><span>{SPARK_HOURS} h response time</span>'
        f'<span>min {lo} · avg {avg} · max {hi} ms</span></figcaption></figure>'
    )


def _pill(status: str | None) -> str:
    s = status or "unknown"
    text = stats.STATUS_TEXT.get(status, "No data")
    return (f'<span class="pill st-{s}" data-field="status"><span class="pill-icon" aria-hidden="true">'
            f'{STATUS_ICON.get(s, "")}</span><span class="pill-text">{text}</span></span>')


def _monitor_card(m: dict, series: dict, incident: dict | None, level: int = 3) -> str:
    slug = escape(m["slug"])
    name = escape(m["name"])
    up = m.get("uptime") or {}
    ms = m.get("avg_ms") or {}
    url = m.get("url") or ""
    url_html = f'<a class="m-url" href="{escape(url)}" rel="noopener">{escape(url)}</a>' if url.startswith("http") and "${" not in url else ""
    desc = f'<p class="m-desc">{escape(m.get("description") or "")}</p>' if m.get("description") else ""
    inc = ""
    if incident:
        inc = (f'<p class="m-incident"><a href="{escape(incident.get("url") or "#")}">Incident '
               f'#{incident["number"]} is open</a></p>')
    rows = []
    for key, label in (("24h", "24 hours"), ("7d", "7 days"), ("30d", "30 days"), ("90d", "90 days"), ("all", "All time")):
        rows.append(f'<div><dt>{label}</dt><dd data-field="uptime.{key}">{stats.fmt_pct(up.get(key))}</dd></div>')
    status = m.get("status")
    code = m.get("code")
    last = (f'Last check {_time(m.get("checked_at"), "checked_at")}: '
            f'<span data-field="code">{"HTTP " + str(code) if code else "no response"}</span> in '
            f'<span data-field="ms">{_ms(m.get("ms"))}</span>') if m.get("checked_at") else "Not checked yet"
    change = ""
    lc = m.get("last_change")
    if lc and lc.get("at"):
        change = f' · {escape(stats.STATUS_TEXT.get(lc.get("to"), "changed"))} since {_time(lc["at"], "since")}'
    return f"""
<li class="card st-{status or 'unknown'}" id="m-{slug}" data-slug="{slug}">
  <div class="card-head">
    <h{level}>{name}</h{level}>
    {_pill(status)}
  </div>
  {url_html}{desc}{inc}
  <div class="history">
    {_bars(m["name"], series["daily"])}
    <div class="bar-scale" aria-hidden="true"><span>{HISTORY_DAYS} days ago</span><span class="bar-scale-mid" data-field="uptime.90d-text">{stats.fmt_pct(up.get("90d"))} uptime</span><span>Today</span></div>
  </div>
  <div class="card-foot">
    <dl class="uptimes" aria-label="Uptime for {name}">{"".join(rows)}</dl>
    <div class="perf">
      {_spark(m["name"], series["hourly"])}
      <p class="avg">Average response (24 h): <strong data-field="avg_ms.24h">{_ms(ms.get("24h"))}</strong></p>
    </div>
  </div>
  <p class="last">{last}{change}</p>
</li>"""


def _link_card(link, level: int = 4) -> str:
    """A plain link card: no status pill, bars or uptime. External, so rel="noopener"."""
    desc = f'<p class="l-desc">{escape(link.description)}</p>' if link.description else ""
    return f"""
<li class="card link-card">
  <h{level}><a class="l-name" href="{escape(link.url)}" rel="noopener">{escape(link.name)}</a></h{level}>
  <span class="m-url">{escape(link.url)}</span>{desc}
</li>"""


def _group(group, status: str | None, cards: list[str], links: list[str] | None = None) -> str:
    """A collapsible section of monitor cards (and plain link cards) with a combined status pill.

    A group with only links has no status (``status`` is None): no pill, neutral accent.
    """
    links = links or []
    slug = escape(group.slug)
    # Collapsed groups still open themselves when something inside needs attention.
    is_open = not group.collapsed or status in ("down", "partial", "degraded")
    desc = f'<p class="group-desc">{escape(group.description)}</p>' if group.description else ""
    counts = []
    if cards:
        counts.append(f'{len(cards)} monitor{"" if len(cards) == 1 else "s"}')
    if links:
        counts.append(f'{len(links)} link{"" if len(links) == 1 else "s"}')
    pill = (f'<span class="pill st-{status}" data-field="group-status"><span class="pill-icon" aria-hidden="true">'
            f'{STATUS_ICON[status]}</span><span class="pill-text">{GROUP_TEXT[status]}</span></span>') if status else ""
    # Link-only groups carry no data-group, so the live-refresh script leaves them alone.
    attrs = f' data-group="{slug}"' if status else ""
    body = f'<ul class="monitors">{"".join(cards)}</ul>' if cards else ""
    body += f'<ul class="monitors links">{"".join(links)}</ul>' if links else ""
    return f"""
<li class="group st-{status or "none"}" id="g-{slug}"{attrs}>
<details{" open" if is_open else ""}>
  <summary>
    <span class="group-title"><h3>{escape(group.name)}</h3><span class="group-count">{" · ".join(counts)}</span></span>{pill}
  </summary>
  {desc}{body}
</details>
</li>"""


def _incidents(incidents: list[dict], names: dict[str, str], now: int) -> tuple[str, str]:
    open_items = [i for i in incidents if i["state"] == "open"]
    cutoff = now - HISTORY_DAYS * 86400
    closed = [i for i in incidents if i["state"] != "open" and (i.get("opened") or 0) >= cutoff][:10]

    def item(i: dict) -> str:
        mon = names.get(i.get("slug") or "", "")
        mon_html = f'<span class="inc-mon">{escape(mon)}</span>' if mon else ""
        if i["state"] == "open":
            when = f'Started {_time(i.get("opened"))}'
            badge = '<span class="pill st-down"><span class="pill-icon" aria-hidden="true">✖</span><span class="pill-text">Ongoing</span></span>'
        else:
            took = duration((i.get("closed") or 0) - (i.get("opened") or 0)) if i.get("closed") and i.get("opened") else ""
            when = f'{_time(i.get("opened"))}' + (f" · resolved after {took}" if took else "")
            badge = '<span class="pill st-up"><span class="pill-icon" aria-hidden="true">✔</span><span class="pill-text">Resolved</span></span>'
        return (f'<li class="inc inc-{escape(i["state"])}"><div class="inc-head"><a href="{escape(i["url"])}">'
                f'{escape(i["title"])}</a>{badge}</div><p class="inc-meta">{mon_html}{when}</p></li>')

    ongoing = ""
    if open_items:
        ongoing = ('<section class="ongoing" aria-labelledby="ongoing-h"><h2 id="ongoing-h">Ongoing incidents</h2>'
                   '<ul class="inc-list">' + "".join(item(i) for i in open_items) + "</ul></section>")
    recent = ('<section class="recent" aria-labelledby="recent-h"><h2 id="recent-h">Recent incidents</h2>'
              + ('<ul class="inc-list">' + "".join(item(i) for i in closed) + "</ul>" if closed
                 else f'<p class="muted">No incidents in the last {HISTORY_DAYS} days.</p>')
              + "</section>")
    return ongoing, recent


# --------------------------------------------------------------------------
# page


_DARK_TOKENS = """
  --bg:#0d1117; --bg-soft:#151b23; --card:#161b22; --border:#2a313c; --text:#e6edf3; --muted:#9198a1;
  --accent:{accent_dark}; --accent-strong:{accent_dark}; --on-accent:{on_accent_dark}; --accent-soft:{accent_soft_dark};
  --up:#3fb950; --degraded:#d29922; --down:#f85149; --unknown:#8b949e;
  --lvl-ok:#2ea043; --lvl-degraded:#bb8009; --lvl-minor:#db6d28; --lvl-major:#da3633; --lvl-none:#30363d;
  --shadow:0 1px 0 rgba(255,255,255,.03), 0 8px 24px rgba(0,0,0,.35);
  color-scheme: dark;
"""

_CSS = """
:root{
  --bg:#f6f7f9; --bg-soft:#eef0f3; --card:#ffffff; --border:#dfe3e8; --text:#1f2328; --muted:#59636e;
  --accent:{accent}; --accent-strong:{accent_light}; --on-accent:{on_accent}; --accent-soft:{accent_soft};
  --up:#1a7f37; --degraded:#9a6700; --down:#cf222e; --unknown:#6e7781;
  --lvl-ok:#2da44e; --lvl-degraded:#d4a72c; --lvl-minor:#e16f24; --lvl-major:#cf222e; --lvl-none:#d0d7de;
  --shadow:0 1px 2px rgba(31,35,40,.06), 0 8px 24px rgba(31,35,40,.06);
  --radius:14px; color-scheme: light;
  --font: system-ui, -apple-system, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
}
@media (prefers-color-scheme: dark){ :root:not([data-theme="light"]){ {dark} } }
:root[data-theme="dark"]{ {dark} }
*,*::before,*::after{box-sizing:border-box}
html{-webkit-text-size-adjust:100%}
body{margin:0;background:var(--bg);color:var(--text);font:16px/1.5 var(--font);min-height:100vh;display:flex;flex-direction:column}
a{color:var(--accent-strong)}
a:hover{text-decoration-thickness:2px}
:focus-visible{outline:3px solid var(--accent);outline-offset:2px;border-radius:4px}
.sr-only{position:absolute;width:1px;height:1px;padding:0;margin:-1px;overflow:hidden;clip:rect(0,0,0,0);white-space:nowrap;border:0}
.skip{position:absolute;left:-999px;top:8px;background:var(--card);color:var(--text);padding:8px 12px;border-radius:8px;z-index:10}
.skip:focus{left:8px}
.wrap{width:100%;max-width:880px;margin:0 auto;padding:0 16px}
.top{border-bottom:1px solid var(--border);background:var(--card)}
.top .wrap{display:flex;align-items:center;justify-content:space-between;gap:12px;min-height:64px}
.brand{display:flex;align-items:center;gap:12px;color:var(--text);text-decoration:none;font-weight:700;font-size:18px;min-width:0}
.brand img{height:36px;width:auto;max-width:180px;object-fit:contain}
.brand span{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.theme-toggle{display:inline-flex;align-items:center;gap:8px;border:1px solid var(--border);background:var(--bg-soft);color:var(--text);border-radius:999px;padding:6px 12px;font:inherit;font-size:14px;cursor:pointer}
.theme-toggle:hover{border-color:var(--accent)}
.theme-toggle svg{width:16px;height:16px}
main.wrap{flex:1;padding-top:28px;padding-bottom:40px}
.hero{display:flex;align-items:center;gap:16px;padding:20px 22px;border-radius:var(--radius);background:var(--card);border:1px solid var(--border);box-shadow:var(--shadow);border-left:6px solid var(--unknown)}
.hero h1{margin:0;font-size:clamp(20px,3.6vw,26px);line-height:1.2}
.hero p{margin:4px 0 0;color:var(--muted);font-size:14px}
.hero-icon{flex:none;display:grid;place-items:center;width:44px;height:44px;border-radius:50%;color:#fff;font-size:22px;background:var(--unknown)}
.hero.st-up{border-left-color:var(--up)} .hero.st-up .hero-icon{background:var(--up)}
.hero.st-degraded,.hero.st-partial{border-left-color:var(--degraded)} .hero.st-degraded .hero-icon,.hero.st-partial .hero-icon{background:var(--degraded)}
.hero.st-down{border-left-color:var(--down)} .hero.st-down .hero-icon{background:var(--down)}
.intro{color:var(--muted);margin:18px 2px 0}
h2{font-size:18px;margin:32px 2px 12px}
.monitors,.inc-list{list-style:none;margin:0;padding:0;display:grid;gap:14px}
.card{background:var(--card);border:1px solid var(--border);border-radius:var(--radius);padding:18px 20px;box-shadow:var(--shadow)}
.card-head{display:flex;align-items:center;justify-content:space-between;gap:12px;flex-wrap:wrap}
.card h3,.card h4{margin:0;font-size:17px}
.groups{list-style:none;margin:0;padding:0;display:grid;gap:18px}
.monitors + .groups{margin-top:18px}
.group>details>summary{display:flex;align-items:center;justify-content:space-between;gap:12px;flex-wrap:wrap;cursor:pointer;list-style:none;padding:12px 16px;background:var(--bg-soft);border:1px solid var(--border);border-left:5px solid var(--unknown);border-radius:12px}
.group>details>summary::-webkit-details-marker{display:none}
.group>details>summary:hover{border-color:var(--accent)}
.group.st-up>details>summary{border-left-color:var(--up)}
.group.st-degraded>details>summary,.group.st-partial>details>summary{border-left-color:var(--degraded)}
.group.st-down>details>summary{border-left-color:var(--down)}
.group-title{display:flex;align-items:center;gap:10px;min-width:0}
.group-title::before{content:"";flex:none;width:8px;height:8px;border-right:2px solid var(--muted);border-bottom:2px solid var(--muted);transform:rotate(-45deg);transition:transform .15s ease;margin-right:2px}
.group>details[open]>summary .group-title::before{transform:rotate(45deg)}
.group h3{margin:0;font-size:17px}
.group-count{color:var(--muted);font-size:13px;white-space:nowrap}
.group-desc{margin:10px 2px 0;color:var(--muted);font-size:14px}
.group>details>.monitors{margin-top:12px}
.group>details>.monitors + .monitors{margin-top:14px}
.link-card{padding:14px 20px;display:grid;gap:4px;border-left:4px solid var(--border)}
.link-card:hover,.link-card:focus-within{border-left-color:var(--accent)}
.link-card .l-name{color:var(--text);text-decoration:none;font-weight:600;overflow-wrap:anywhere}
.link-card .l-name:hover,.link-card .l-name:focus-visible{color:var(--accent-strong);text-decoration:underline}
.link-card .m-url{margin:0}
.l-desc{margin:2px 0 0;color:var(--muted);font-size:14px}
.m-url{display:inline-block;margin-top:2px;color:var(--muted);font-size:13px;word-break:break-all}
.m-desc{margin:6px 0 0;color:var(--muted);font-size:14px}
.m-incident{margin:8px 0 0;font-size:14px;font-weight:600}
.m-incident a{color:var(--down)}
.pill{display:inline-flex;align-items:center;gap:6px;font-size:13px;font-weight:600;padding:3px 10px;border-radius:999px;border:1px solid currentColor;white-space:nowrap}
.pill.st-up{color:var(--up)} .pill.st-degraded,.pill.st-partial{color:var(--degraded)} .pill.st-down{color:var(--down)} .pill.st-unknown{color:var(--unknown)}
.pill-icon{font-size:11px}
.history{margin-top:14px}
.bars{list-style:none;margin:0;padding:0;display:flex;gap:2px;height:34px;align-items:stretch}
.bar{flex:1 1 0;min-width:0;border-radius:3px;background:var(--lvl-none);cursor:default;transition:transform .12s ease,opacity .12s}
.bar:hover,.bar:focus{transform:scaleY(1.12);outline-offset:1px}
.bar.lvl-ok{background:var(--lvl-ok)} .bar.lvl-degraded{background:var(--lvl-degraded)}
.bar.lvl-minor{background:var(--lvl-minor)} .bar.lvl-major{background:var(--lvl-major)}
.bar-scale{display:flex;justify-content:space-between;color:var(--muted);font-size:12px;margin-top:6px}
.bar-scale-mid{color:var(--text);font-weight:600}
.card-foot{display:grid;grid-template-columns:1fr 1fr;gap:18px;margin-top:16px;align-items:start}
.uptimes{display:grid;grid-template-columns:repeat(5,1fr);gap:6px;margin:0}
.uptimes div{background:var(--bg-soft);border-radius:10px;padding:8px 6px;text-align:center;min-width:0}
.uptimes dt{font-size:11px;color:var(--muted);text-transform:uppercase;letter-spacing:.04em}
.uptimes dd{margin:2px 0 0;font-weight:700;font-size:14px;font-variant-numeric:tabular-nums}
.spark{margin:0}
.spark svg{display:block;width:100%;height:44px}
.spark-line{fill:none;stroke:var(--accent);stroke-width:1.8;vector-effect:non-scaling-stroke;stroke-linejoin:round;stroke-linecap:round}
.spark-area{fill:var(--accent-soft)}
.spark-dot{fill:var(--accent)}
.spark figcaption{display:flex;justify-content:space-between;gap:8px;font-size:12px;color:var(--muted);margin-top:4px;flex-wrap:wrap}
.spark-empty{margin:0;color:var(--muted);font-size:13px}
.avg{margin:6px 0 0;font-size:13px;color:var(--muted)}
.avg strong{color:var(--text)}
.last{margin:14px 0 0;font-size:13px;color:var(--muted);border-top:1px solid var(--border);padding-top:10px}
.legend{display:flex;flex-wrap:wrap;gap:8px 16px;margin:16px 2px 0;padding:0;list-style:none;font-size:13px;color:var(--muted)}
.legend li{display:inline-flex;align-items:center;gap:6px}
.swatch{width:12px;height:12px;border-radius:3px;display:inline-block;background:var(--lvl-none)}
.swatch.lvl-ok{background:var(--lvl-ok)} .swatch.lvl-degraded{background:var(--lvl-degraded)} .swatch.lvl-minor{background:var(--lvl-minor)} .swatch.lvl-major{background:var(--lvl-major)}
.inc{background:var(--card);border:1px solid var(--border);border-radius:12px;padding:14px 16px}
.inc-open{border-left:5px solid var(--down)}
.inc-head{display:flex;justify-content:space-between;gap:12px;align-items:center;flex-wrap:wrap}
.inc-head a{font-weight:600;color:var(--text)}
.inc-meta{margin:6px 0 0;color:var(--muted);font-size:13px}
.inc-mon{display:inline-block;background:var(--accent-soft);color:var(--text);border-radius:6px;padding:0 6px;margin-right:8px;font-weight:600}
.muted{color:var(--muted)}
footer{border-top:1px solid var(--border);background:var(--card);font-size:14px;color:var(--muted)}
footer .wrap{display:flex;flex-wrap:wrap;gap:8px 20px;justify-content:space-between;align-items:center;padding-top:18px;padding-bottom:18px}
footer nav ul{list-style:none;display:flex;flex-wrap:wrap;gap:6px 18px;margin:0;padding:0}
footer a{color:var(--muted)}
.foot-version{font-variant-numeric:tabular-nums}
footer a:hover{color:var(--accent-strong)}
.copyright{flex:1 0 100%;margin:0;font-size:13px}
.powered{display:flex;flex-wrap:wrap;align-items:center;gap:4px 10px;margin:0}
/* "Powered by GitHup | A Stux.Group Service": muted until hovered or focused, like every Stux footer. */
.powered a{display:inline-flex;align-items:center;gap:8px;color:var(--muted);font-weight:600;text-decoration:none;transition:color .2s}
.powered a:hover,.powered a:focus-visible{color:var(--text)}
.powered-sep{color:var(--border)}
.powered .powered-ver{font-weight:500;font-variant-numeric:tabular-nums;margin-left:-4px}
/* Same filter functions in every state, so hovering animates smoothly (switching the filter off drops the layer and snaps). */
.gh-mark{width:20px;height:20px;flex:none;filter:grayscale(1) brightness(1);opacity:.7;transition:filter .2s ease,opacity .2s ease;will-change:filter,opacity;backface-visibility:hidden;transform:translateZ(0)}
:root[data-theme="light"] .gh-mark{filter:grayscale(1) brightness(.6)}
@media (prefers-color-scheme: light){:root:not([data-theme="dark"]) .gh-mark{filter:grayscale(1) brightness(.6)}}
:root .powered a:hover .gh-mark,:root .powered a:focus-visible .gh-mark{filter:grayscale(0) brightness(1);opacity:1}
#tip{position:fixed;z-index:20;pointer-events:none;max-width:260px;background:var(--text);color:var(--bg);font-size:12px;line-height:1.45;padding:8px 10px;border-radius:8px;white-space:pre-line;box-shadow:0 6px 18px rgba(0,0,0,.25)}
#tip[hidden]{display:none}
@media (max-width:720px){
  .card-foot{grid-template-columns:1fr}
  .bars{gap:1px;height:30px}
  .bar{border-radius:2px}
}
@media (max-width:480px){
  .uptimes{grid-template-columns:repeat(3,1fr)}
  .hero{padding:16px}
  .theme-toggle .tt-text{display:none}
  .card{padding:16px}
}
@media (prefers-reduced-motion:reduce){*{transition:none!important}}
"""

_THEME_BOOT = """(function(){try{var t=localStorage.getItem('githup-theme');if(t==='light'||t==='dark')document.documentElement.setAttribute('data-theme',t);}catch(e){}})();"""

_JS = r"""
(function(){
  'use strict';
  var root=document.documentElement, cfg={};
  try{cfg=JSON.parse(document.getElementById('githup-config').textContent);}catch(e){}

  /* theme toggle */
  var btn=document.getElementById('theme-toggle');
  var mq=window.matchMedia?window.matchMedia('(prefers-color-scheme: dark)'):null;
  function effective(){var t=root.getAttribute('data-theme');if(t==='light'||t==='dark')return t;return mq&&mq.matches?'dark':'light';}
  function syncToggle(){if(!btn)return;var dark=effective()==='dark';btn.setAttribute('aria-pressed',dark?'true':'false');
    btn.setAttribute('aria-label','Switch to '+(dark?'light':'dark')+' theme');btn.querySelector('.tt-text').textContent=dark?'Light':'Dark';}
  if(btn){btn.addEventListener('click',function(){var next=effective()==='dark'?'light':'dark';root.setAttribute('data-theme',next);
    try{localStorage.setItem('githup-theme',next);}catch(e){}syncToggle();});}
  if(mq&&mq.addEventListener)mq.addEventListener('change',syncToggle);
  syncToggle();

  /* relative times */
  function ago(ts){var s=Math.round(Date.now()/1000-ts);if(s<45)return 'just now';var m=Math.round(s/60);if(m<60)return m+' min ago';
    var h=Math.round(m/60);if(h<48)return h+' h ago';return Math.round(h/24)+' days ago';}
  function tick(){var els=document.querySelectorAll('time[data-ts]');for(var i=0;i<els.length;i++){var ts=+els[i].getAttribute('data-ts');
    if(!ts)continue;var d=new Date(ts*1000);els[i].textContent=ago(ts);els[i].title=d.toLocaleString();}}
  tick();setInterval(tick,30000);

  /* bar tooltips + keyboard navigation */
  var tip=document.getElementById('tip');
  function place(el){var r=el.getBoundingClientRect();tip.hidden=false;var tw=tip.offsetWidth,th=tip.offsetHeight;
    var x=Math.min(Math.max(8,r.left+r.width/2-tw/2),window.innerWidth-tw-8);var y=r.top-th-8;if(y<8)y=r.bottom+8;
    tip.style.left=x+'px';tip.style.top=y+'px';}
  function show(el){tip.textContent=el.getAttribute('data-tip');place(el);}
  function hide(){tip.hidden=true;}
  var lists=document.querySelectorAll('.bars');
  for(var i=0;i<lists.length;i++){(function(list){
    list.addEventListener('mouseover',function(e){var li=e.target.closest('.bar');if(li)show(li);});
    list.addEventListener('mouseleave',hide);
    list.addEventListener('focusin',function(e){var li=e.target.closest('.bar');if(li)show(li);});
    list.addEventListener('focusout',hide);
    list.addEventListener('keydown',function(e){var li=e.target.closest('.bar');if(!li)return;var bars=list.querySelectorAll('.bar');
      var idx=Array.prototype.indexOf.call(bars,li),next=idx;
      if(e.key==='ArrowLeft')next=idx-1;else if(e.key==='ArrowRight')next=idx+1;else if(e.key==='Home')next=0;else if(e.key==='End')next=bars.length-1;
      else if(e.key==='Escape'){hide();return;}else return;
      e.preventDefault();next=Math.max(0,Math.min(bars.length-1,next));li.tabIndex=-1;bars[next].tabIndex=0;bars[next].focus();});
  })(lists[i]);}
  window.addEventListener('scroll',hide,{passive:true});

  /* live refresh from summary.json */
  var TEXT={up:'Operational',degraded:'Degraded',down:'Down'};
  var ICON={up:'✔',degraded:'▲',down:'✖',partial:'▲',unknown:'•'};
  var GROUP={up:'Operational',degraded:'Degraded',partial:'Partial outage',down:'Down',unknown:'No data'};
  var OVERALL={up:'All systems operational',degraded:'Degraded performance',partial:'Partial outage',down:'Major outage',unknown:'No data yet'};
  function pct(v){if(v===null||v===undefined)return 'n/a';return (Math.floor(v*100+1e-9)/100).toFixed(2)+'%';}
  function ms(v){return v===null||v===undefined?'n/a':v.toLocaleString('en')+' ms';}
  function setStatusClass(el,s){el.className=el.className.replace(/\bst-[a-z]+\b/g,'').trim()+' st-'+s;}
  function apply(s){
    if(!s||!s.monitors||(cfg.updated&&s.updated<cfg.updated))return;
    cfg.updated=s.updated;
    var hero=document.getElementById('hero');
    if(hero){setStatusClass(hero,s.status||'unknown');document.getElementById('overall-text').textContent=OVERALL[s.status]||OVERALL.unknown;
      hero.querySelector('.hero-icon').textContent=ICON[s.status]||ICON.unknown;
      var up=document.getElementById('updated');if(up){up.setAttribute('data-ts',s.updated);}}
    s.monitors.forEach(function(m){var card=document.getElementById('m-'+m.slug);if(!card)return;var st=m.status||'unknown';
      setStatusClass(card,st);var pill=card.querySelector('[data-field="status"]');
      if(pill){setStatusClass(pill,st);pill.querySelector('.pill-text').textContent=TEXT[m.status]||'No data';pill.querySelector('.pill-icon').textContent=ICON[st]||'';}
      ['24h','7d','30d','90d','all'].forEach(function(k){var el=card.querySelector('[data-field="uptime.'+k+'"]');if(el&&m.uptime)el.textContent=pct(m.uptime[k]);});
      var t=card.querySelector('[data-field="uptime.90d-text"]');if(t&&m.uptime)t.textContent=pct(m.uptime['90d'])+' uptime';
      var a=card.querySelector('[data-field="avg_ms.24h"]');if(a&&m.avg_ms)a.textContent=ms(m.avg_ms['24h']);
      var c=card.querySelector('[data-field="code"]');if(c)c.textContent=m.code?'HTTP '+m.code:'no response';
      var r=card.querySelector('[data-field="ms"]');if(r)r.textContent=ms(m.ms);
      var ca=card.querySelector('[data-field="checked_at"]');if(ca&&m.checked_at)ca.setAttribute('data-ts',m.checked_at);
    });
    var by={};s.monitors.forEach(function(m){by[m.slug]=m.status;});
    var groups=document.querySelectorAll('.group[data-group]');
    for(var g=0;g<groups.length;g++){var grp=groups[g],cards=grp.querySelectorAll('.card[data-slug]'),known=[],downs=0;
      for(var c2=0;c2<cards.length;c2++){var gs=by[cards[c2].getAttribute('data-slug')];if(gs==='up'||gs==='degraded'||gs==='down'){known.push(gs);if(gs==='down')downs++;}}
      var gst=!known.length?'unknown':downs===known.length?'down':downs?'partial':known.indexOf('degraded')>=0?'degraded':'up';
      setStatusClass(grp,gst);var gp=grp.querySelector('[data-field="group-status"]');
      if(gp){setStatusClass(gp,gst);gp.querySelector('.pill-text').textContent=GROUP[gst];gp.querySelector('.pill-icon').textContent=ICON[gst];}
      if(gst==='down'||gst==='partial'){var det=grp.querySelector('details');if(det)det.open=true;}}
    tick();
  }
  function get(url){return fetch(url+(url.indexOf('?')<0?'?':'&')+'t='+Date.now(),{cache:'no-store'}).then(function(r){if(!r.ok)throw new Error(r.status);return r.json();});}
  function refresh(){if(document.hidden)return;var p=cfg.live?get(cfg.live).catch(function(){return get('summary.json');}):get('summary.json');p.then(apply).catch(function(){});}
  if(cfg.refresh>0&&window.fetch){setInterval(refresh,cfg.refresh*1000);document.addEventListener('visibilitychange',function(){if(!document.hidden)refresh();});}
})();
"""

_SUN = '<svg viewBox="0 0 24 24" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/></svg>'


def css_for(accent: str) -> str:
    light_bg, dark_bg = "#ffffff", "#161b22"
    accent_light = readable(accent, light_bg)
    accent_dark = readable(accent, dark_bg)
    dark = (_DARK_TOKENS.replace("{accent_dark}", accent_dark)
            .replace("{on_accent_dark}", on_colour(accent_dark))
            .replace("{accent_soft_dark}", _mix(dark_bg, accent_dark, 0.22)))
    return (_CSS.replace("{dark}", dark)
            .replace("{accent}", accent)
            .replace("{accent_light}", accent_light)
            .replace("{on_accent}", on_colour(accent))
            .replace("{accent_soft}", _mix("#ffffff", accent, 0.16)))


def banner_css_for(accent: str) -> str:
    """The shared banner CSS, with the page's colours mapped onto its theme hooks."""
    hooks = (".site-banners{--banner-page-bg:var(--bg);--banner-text:var(--text);"
             f"--banner-site:{readable(accent, '#0d1117')};--banner-site-light:{readable(accent, '#f6f7f9')}}}")
    return BANNER_CSS + "\n" + hooks


# Stack order when several banners apply: maintenance, soon, dev, site.
BANNER_ORDER = ("maintenance", "soon", "dev", "site")


def banners(site, dev_mode: bool) -> str:
    """The banners this build shows: dev mode locally, and the site notice when one is set."""
    items = []
    if dev_mode:
        items.append(("dev", "Dev mode", f"Local preview of {escape(site.name)}, built from example data. "
                      "Run <code>dev-server.sh --no-dev-mode</code> to see it as production does."))
    if site.notice:
        items.append(("site", "Notice", escape(site.notice)))
    if not items:
        return ""
    return ('<div class="site-banners" data-site-banners>'
            + "".join(f'<div class="site-banner site-banner--{v}" role="note"><span class="site-banner-label">{label}</span>'
                      f'<span class="site-banner-text">{text}</span></div>' for v, label, text in items)
            + "</div>")


# Dev mode only: ?banner=soon,maintenance,site previews the other banners locally.
_BANNER_PREVIEW_JS = r"""
(function(){
  var want=(new URLSearchParams(location.search).get('banner')||'').split(','),box=document.querySelector('[data-site-banners]');
  if(!box)return;
  var name=document.title,copy={maintenance:['Maintenance',name+' is being updated and will be back shortly.'],
    soon:['Coming soon',name+' is launching soon.'],site:['Notice','A site notice for '+name+' appears here.']};
  var order=['maintenance','soon','dev','site'];
  want.forEach(function(v){
    if(!copy[v]||box.querySelector('.site-banner--'+v))return;
    var d=document.createElement('div');d.className='site-banner site-banner--'+v;d.setAttribute('role','note');
    var l=document.createElement('span');l.className='site-banner-label';l.textContent=copy[v][0];
    var t=document.createElement('span');t.className='site-banner-text';t.textContent=copy[v][1];
    d.appendChild(l);d.appendChild(t);
    var next=null;for(var i=0;i<box.children.length;i++){var m=/site-banner--(\w+)/.exec(box.children[i].className);
      if(m&&order.indexOf(m[1])>order.indexOf(v)){next=box.children[i];break;}}
    box.insertBefore(d,next);
  });
})();
"""


def render(config, summary: dict, series: dict[str, dict], incidents: list[dict], *, now: int,
           dev_mode: bool = False, live_url: str = "") -> str:
    site = config.site
    index = stats.summary_index(summary)
    names = {mon.slug: mon.name for mon in config.monitors}

    def card(mon, level: int) -> str:
        m = dict(index.get(mon.slug) or {"slug": mon.slug, "name": mon.name, "status": None})
        m["name"] = mon.name
        m["description"] = mon.description
        show = mon.show_url if mon.show_url is not None else site.show_urls
        m["url"] = mon.url if show else ""
        s = series.get(mon.slug) or {"daily": stats.daily([], now, HISTORY_DAYS), "hourly": [None] * SPARK_HOURS}
        return _monitor_card(m, s, m.get("incident"), level)

    ungrouped, groups = "", []
    for group, members in config.sections():
        if group is None:
            ungrouped = '<ul class="monitors">' + "".join(card(mon, 3) for mon in members) + "\n    </ul>"
        else:
            status = (stats.overall([(index.get(mon.slug) or {}).get("status") for mon in members])
                      if members else None)
            groups.append(_group(group, status, [card(mon, 4) for mon in members],
                                 [_link_card(link) for link in group.links]))
    monitors_html = ungrouped + (f'<ul class="groups">{"".join(groups)}\n    </ul>' if groups else "")
    overall = stats.overall([(index.get(mon.slug) or {}).get("status") for mon in config.monitors])
    ongoing, recent = _incidents(incidents, names, now)
    updated = summary.get("updated")
    updated_html = (f'<time id="updated" datetime="{_iso(updated)}" data-ts="{updated}">{_utc(updated)}</time>'
                    if updated else "never")

    logo = f'<img src="{escape(site.logo)}" alt="">' if site.logo else ""
    favicon = f'<link rel="icon" href="{escape(site.favicon or site.logo or GITHUP_FAVICON)}">'
    desc_meta = escape(site.description or f"Live status and uptime history for {site.name}.")
    intro = f'<p class="intro">{escape(site.description)}</p>' if site.description else ""
    banner_html = banners(site, dev_mode)
    html_class = ' class="has-site-banner"' if banner_html else ""
    # The shared banner CSS/JS only ship when a banner is shown, so normal pages stay lean.
    banner_style = f"<style>{banner_css_for(site.accent)}</style>\n" if banner_html else ""
    banner_js = ((_BANNER_PREVIEW_JS if dev_mode else "") + BANNER_JS) if banner_html else ""

    footer_html = _footer(config, "./", datetime.fromtimestamp(now, timezone.utc).year)

    page_cfg = {"refresh": site.refresh, "live": "" if dev_mode else live_url, "updated": updated or 0,
                "version": __version__}
    cfg_json = json.dumps(page_cfg).replace("</", "<\\/")
    connect = "'self'" + (" https://raw.githubusercontent.com" if live_url and not dev_mode else "")
    csp = (f"default-src 'none'; img-src 'self' https: data:; style-src 'unsafe-inline'; "
           f"script-src 'unsafe-inline'; connect-src {connect}; base-uri 'none'; form-action 'none'")
    legend = "".join(f'<li><span class="swatch lvl-{k}" aria-hidden="true"></span>{v}</li>' for k, v in LEVEL_TEXT.items())

    return f"""<!doctype html>
<html lang="en"{html_class}>
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta http-equiv="Content-Security-Policy" content="{csp}">
<title>{escape(site.name)}</title>
<meta name="description" content="{desc_meta}">
<meta name="theme-color" content="{site.accent}">
<meta name="generator" content="GitHup {__version__}">
{favicon}
<script>{_THEME_BOOT}</script>
<style>{css_for(site.accent)}</style>
{banner_style}</head>
<body>
{banner_html}
<a class="skip" href="#main">Skip to content</a>
<header class="top">
  <div class="wrap">
    <a class="brand" href="./">{logo}<span>{escape(site.name)}</span></a>
    <button type="button" class="theme-toggle" id="theme-toggle" aria-pressed="false" aria-label="Toggle dark theme">{_SUN}<span class="tt-text">Dark</span></button>
  </div>
</header>
<main id="main" class="wrap">
  <section id="hero" class="hero st-{overall}" role="status" aria-live="polite" aria-atomic="true">
    <span class="hero-icon" aria-hidden="true">{STATUS_ICON[overall]}</span>
    <div>
      <h1 id="overall-text">{stats.OVERALL_TEXT[overall]}</h1>
      <p>Updated {updated_html}{" · refreshes automatically" if site.refresh else ""} · daily history in UTC</p>
    </div>
  </section>
  {intro}
  {ongoing}
  <section aria-labelledby="monitors-h">
    <h2 id="monitors-h">Monitors</h2>
    {monitors_html}
    <ul class="legend" aria-label="History colour key">{legend}</ul>
  </section>
  {recent}
</main>
{footer_html}
<div id="tip" role="tooltip" hidden></div>
<script type="application/json" id="githup-config">{cfg_json}</script>
<script>{_JS}</script>
{f'<script>{banner_js}</script>' if banner_js else ''}
</body>
</html>
"""


# --------------------------------------------------------------------------
# footer, shared page shell, legal pages, 404, sitemap


def base_url(site) -> str:
    """Canonical base URL with a trailing slash: ``site.cname``, else ``site.url``, else ""."""
    if site.cname:
        return f"https://{site.cname}/"
    return site.url.rstrip("/") + "/" if site.url and not site.url.startswith("${") else ""


def base_path(site) -> str:
    """Where the site root is for pages served from any depth (the 404 page); "./" when unknown."""
    base = base_url(site)
    return (urlparse(base).path or "/") if base else "./"


def copyright_years(start: int | None, year: int) -> str:
    """``2026`` in the start year itself (or with no start), ``2024–2026`` (en dash) after it."""
    return str(year) if start is None or start >= year else f"{start}–{year}"


def _copyright(site, year: int | None) -> str:
    """The footer's "Copyright (c) START–CURRENT HOLDER" line; "" without ``site.copyright``.

    The year comes from the build time (``year``; the current UTC year when not given), and a status
    page is rebuilt at least hourly, so it rolls over on 1 January without any edit.
    """
    c = site.copyright
    if not c:
        return ""
    year = datetime.now(timezone.utc).year if year is None else year
    return f'\n    <p class="copyright">Copyright &copy; {copyright_years(c.start, year)} {escape(c.holder)}</p>'


def _footer(config, root: str, year: int | None = None) -> str:
    site = config.site
    links = [f'<li><a href="{escape(l.url)}">{escape(l.label)}</a></li>' for l in site.footer_links]
    if config.legal:  # the generated pages win over a site.legal URL
        links.append(f'<li><a href="{root}legal/">Boring Legal Stuff</a></li>')
    elif site.legal:
        links.append(f'<li><a href="{escape(site.legal)}">Boring Legal Stuff</a></li>')
    if base_url(site):
        links.append(f'<li><a href="{root}sitemap/">Sitemap</a></li>')
    nav = f'<nav aria-label="Footer"><ul>{"".join(links)}</ul></nav>' if links else ""
    return f"""<footer>
  <div class="wrap">
    {nav}
    <p class="powered"><a href="{GITHUP_URL}">{GITHUP_ICON}Powered by GitHup</a><a class="powered-ver" href="{CHANGELOGS_URL}">v{__version__}</a><span class="powered-sep" aria-hidden="true">|</span><a href="{SERVICES_URL}">A Stux.Group Service</a></p>{_copyright(site, year)}
  </div>
</footer>"""


_PAGE_CSS = """
.doc{max-width:720px}
.crumbs{margin:0 0 6px;color:var(--muted);font-size:14px}
.doc h1{margin:0;font-size:clamp(24px,4vw,32px);line-height:1.2}
.doc .sub{margin:6px 0 0;color:var(--muted)}
.doc .eff{margin:4px 0 0;color:var(--muted);font-size:13px}
.doc h2{font-size:18px;margin:28px 0 8px}
.doc p{margin:8px 0}
.doc code{background:var(--bg-soft);border-radius:4px;padding:1px 5px;font-size:.92em}
.back{margin-top:32px}
.page-list{list-style:none;margin:24px 0 0;padding:0;display:grid;gap:12px}
.page-list a{display:block;background:var(--card);border:1px solid var(--border);border-radius:12px;padding:14px 18px;text-decoration:none;color:var(--text);box-shadow:var(--shadow)}
.page-list a:hover,.page-list a:focus-visible{border-color:var(--accent)}
.page-list strong{display:block;font-size:17px}
.page-list span{display:block;color:var(--muted);font-size:14px;margin-top:2px}
.page-list .url{font-size:12px;word-break:break-all}
"""
# The theme toggle is the first block of the status page's script; the other pages only need that.
_JS_THEME = _JS.split("  /* relative times */")[0] + "})();\n"


def _shell(config, *, title: str, description: str, main: str, root: str, dev_mode: bool,
           canonical: str = "", year: int | None = None) -> str:
    """A themed page (header, banners, footer) around ``main``, with inline CSS/JS only."""
    site = config.site
    banner_html = banners(site, dev_mode)
    html_class = ' class="has-site-banner"' if banner_html else ""
    banner_style = f"<style>{banner_css_for(site.accent)}</style>\n" if banner_html else ""
    banner_js = ((_BANNER_PREVIEW_JS if dev_mode else "") + BANNER_JS) if banner_html else ""
    logo = f'<img src="{escape(site.logo)}" alt="">' if site.logo else ""
    favicon = f'<link rel="icon" href="{escape(site.favicon or site.logo or GITHUP_FAVICON)}">'
    canon = f'<link rel="canonical" href="{escape(canonical)}">\n' if canonical else ""
    csp = ("default-src 'none'; img-src 'self' https: data:; style-src 'unsafe-inline'; "
           "script-src 'unsafe-inline'; base-uri 'none'; form-action 'none'")
    return f"""<!doctype html>
<html lang="en"{html_class}>
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta http-equiv="Content-Security-Policy" content="{csp}">
<title>{escape(title)} - {escape(site.name)}</title>
<meta name="description" content="{escape(description)}">
<meta name="theme-color" content="{site.accent}">
<meta name="generator" content="GitHup {__version__}">
{canon}{favicon}
<script>{_THEME_BOOT}</script>
<style>{css_for(site.accent)}{_PAGE_CSS}</style>
{banner_style}</head>
<body>
{banner_html}
<a class="skip" href="#main">Skip to content</a>
<header class="top">
  <div class="wrap">
    <a class="brand" href="{root}">{logo}<span>{escape(site.name)}</span></a>
    <button type="button" class="theme-toggle" id="theme-toggle" aria-pressed="false" aria-label="Toggle dark theme">{_SUN}<span class="tt-text">Dark</span></button>
  </div>
</header>
<main id="main" class="wrap">
{main}
</main>
{_footer(config, root, year)}
<script>{_JS_THEME}</script>
{f'<script>{banner_js}</script>' if banner_js else ''}
</body>
</html>
"""


def _crumbs(root: str, site, *trail: tuple[str, str]) -> str:
    parts = [f'<a href="{root}">{escape(site.name)}</a>']
    parts += [f'<a href="{href}">{escape(label)}</a>' if href else escape(label) for label, href in trail]
    return f'<p class="crumbs">{" / ".join(parts)}</p>'


def _list(items: list[tuple[str, str, str, str]]) -> str:
    """Cards of (href, label, description, shown url)."""
    return '<ul class="page-list">' + "".join(
        f'<li><a href="{escape(href)}"><strong>{escape(label)}</strong><span>{escape(desc)}</span>'
        + (f'<span class="url">{escape(url)}</span>' if url else "") + "</a></li>"
        for href, label, desc, url in items) + "</ul>"


def legal_pages(config, *, dev_mode: bool = False, year: int | None = None) -> dict[str, str]:
    """``{relative path: html}`` for the legal hub and its six sub-pages ({} without ``legal:``)."""
    if not config.legal:
        return {}
    site = config.site
    base = base_url(site)
    eff = f'<p class="eff">Effective: {escape(config.legal.effective)}</p>' if config.legal.effective else ""
    out: dict[str, str] = {}
    hub_sub = legal_texts.HUB_SUB.format(name=escape(site.name))
    cards = _list([(f"{slug}/", title, desc, "") for slug, title, desc in legal_texts.PAGES])
    out["legal/index.html"] = _shell(
        config, title="Boring Legal Stuff", description=f"The fine print for {site.name}.", root="../",
        dev_mode=dev_mode, canonical=base + "legal/" if base else "", year=year,
        main=f'<div class="doc">{_crumbs("../", site, ("Boring Legal Stuff", ""))}<h1>Boring Legal Stuff</h1>'
             f'<p class="sub">{hub_sub}</p>{eff}{cards}</div>')
    for slug, title, desc in legal_texts.PAGES:
        out[f"legal/{slug}/index.html"] = _shell(
            config, title=title, description=desc, root="../../", dev_mode=dev_mode,
            canonical=f"{base}legal/{slug}/" if base else "", year=year,
            main=f'<div class="doc">{_crumbs("../../", site, ("Boring Legal Stuff", "../"), (title, ""))}'
                 f'<h1>{escape(title)}</h1><p class="sub">{escape(desc)}</p>{eff}'
                 f'{legal_texts.body(slug, config)}'
                 '<p class="back"><a href="../">&larr; Back to Boring Legal Stuff</a></p></div>')
    return out


def not_found_page(config, *, dev_mode: bool = False, year: int | None = None) -> str:
    """The themed 404. It can be served from any depth, so its links use the site root when known."""
    root = base_path(config.site)
    main = ('<div class="doc"><p class="crumbs">Error 404</p><h1>Page not found</h1>'
            '<p class="sub">That page does not exist, or it has moved.</p>'
            f'<p class="back"><a href="{root}">&larr; Go to the status page</a></p></div>')
    return _shell(config, title="Page not found", description="This page could not be found.", root=root,
                  dev_mode=dev_mode, main=main, year=year)


def sitemap_entries(config) -> list[tuple[str, str, str]]:
    """(relative path, label, description) for every page worth listing."""
    site = config.site
    entries = [("", site.name, site.description or f"Live status and uptime history for {site.name}.")]
    if config.legal:
        entries.append(("legal/", "Boring Legal Stuff", legal_texts.HUB_SUB.format(name=site.name)))
        entries += [(f"legal/{slug}/", title, desc) for slug, title, desc in legal_texts.PAGES]
    return entries


def sitemap_xml(config) -> str:
    base = base_url(config.site)
    urls = "".join(f"  <url><loc>{xml_escape(base + path)}</loc></url>\n" for path, _, _ in sitemap_entries(config))
    return ('<?xml version="1.0" encoding="UTF-8"?>\n'
            f'<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n{urls}</urlset>\n')


def sitemap_page(config, *, dev_mode: bool = False, year: int | None = None) -> str:
    site, base = config.site, base_url(config.site)
    cards = _list([("../" + path, label, desc, base + path) for path, label, desc in sitemap_entries(config)])
    main = (f'<div class="doc">{_crumbs("../", site, ("Sitemap", ""))}<h1>Sitemap</h1>'
            f'<p class="sub">Every page on {escape(site.name)}.</p>{cards}</div>')
    return _shell(config, title="Sitemap", description=f"Every page on {site.name}.", root="../", dev_mode=dev_mode,
                  main=main, canonical=base + "sitemap/", year=year)


def series_for(store, slug: str, now: int) -> dict:
    checks = store.load(slug, since=now - HISTORY_DAYS * 86400 - 86400)
    return {"daily": stats.daily(checks, now, HISTORY_DAYS), "hourly": stats.hourly_ms(checks, now, SPARK_HOURS)}


def build(config, store, out_dir, *, now: int, incidents: list[dict] | None = None,
          dev_mode: bool = False, live_url: str = "", log=lambda msg: None) -> Path:
    """Write the site into ``out_dir`` (emptied first) and return its path."""
    out = Path(out_dir)
    # An existing robots.txt in the output dir is the owner's: keep it as it is.
    robots_file = out / "robots.txt"
    kept_robots = robots_file.read_text(encoding="utf-8") if robots_file.is_file() else None
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)
    summary = store.read_summary()
    series = {m.slug: series_for(store, m.slug, now) for m in config.monitors}
    html = render(config, summary, series, incidents or [], now=now, dev_mode=dev_mode, live_url=live_url)
    (out / "index.html").write_text(html, encoding="utf-8", newline="\n")
    (out / "summary.json").write_text(json.dumps(summary, separators=(",", ":")) + "\n", encoding="utf-8")
    year = datetime.fromtimestamp(now, timezone.utc).year
    extra = legal_pages(config, dev_mode=dev_mode, year=year)
    extra["404.html"] = not_found_page(config, dev_mode=dev_mode, year=year)
    base = base_url(config.site)
    if base:
        extra["sitemap/index.html"] = sitemap_page(config, dev_mode=dev_mode, year=year)
        extra["sitemap.xml"] = sitemap_xml(config)
        extra["robots.txt"] = kept_robots if kept_robots is not None else f"User-agent: *\nAllow: /\n\nSitemap: {base}sitemap.xml\n"
    else:
        log("No site.cname or site.url: skipping sitemap.xml, robots.txt and /sitemap/.")
        if kept_robots is not None:
            extra["robots.txt"] = kept_robots
    for rel, text in extra.items():
        target = out / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8", newline="\n")
    if config.site.cname:
        (out / "CNAME").write_text(config.site.cname + "\n", encoding="utf-8")
    (out / ".nojekyll").write_text("", encoding="utf-8")
    return out
