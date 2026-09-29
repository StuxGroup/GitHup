"""Keep a status table in the consumer's README between two markers::

    <!-- githup:start -->
    (generated table)
    <!-- githup:end -->
"""

from __future__ import annotations

from . import stats

START = "<!-- githup:start -->"
END = "<!-- githup:end -->"
_STATUS = {"up": "Up", "degraded": "Degraded", "down": "**Down**"}


def _cell(text: str) -> str:
    return text.replace("|", "\\|").replace("\n", " ")


def table(config, summary: dict, site_url: str = "") -> str:
    index = stats.summary_index(summary)
    lines = [
        "| Monitor | Status | Uptime (24 h) | Uptime (7 d) | Uptime (30 d) | Response time (24 h) |",
        "| ------- | ------ | ------------- | ------------ | ------------- | -------------------- |",
    ]
    for mon in config.monitors:
        m = index.get(mon.slug) or {}
        show = mon.show_url if mon.show_url is not None else config.site.show_urls
        name = f"[{_cell(mon.name)}]({mon.url})" if show and "${" not in mon.url else _cell(mon.name)
        up = m.get("uptime") or {}
        ms = (m.get("avg_ms") or {}).get("24h")
        lines.append(
            f"| {name} | {_STATUS.get(m.get('status'), 'No data')} | {stats.fmt_pct(up.get('24h'))} | "
            f"{stats.fmt_pct(up.get('7d'))} | {stats.fmt_pct(up.get('30d'))} | "
            f"{'n/a' if ms is None else f'{ms} ms'} |"
        )
    overall = stats.OVERALL_TEXT[summary.get("status") or "unknown"] if summary.get("status") in stats.OVERALL_TEXT else stats.OVERALL_TEXT["unknown"]
    head = f"**{overall}**"
    if site_url:
        head += f" · [Live status page]({site_url})"
    return "\n".join([
        "<!-- This table is written by GitHup (https://github.com/StuxGroup/GitHup); edits here are overwritten. -->",
        "",
        head,
        "",
        *lines,
    ])


def update(text: str, block: str) -> str | None:
    """Replace what is between the markers. Returns None if the markers are missing."""
    start = text.find(START)
    end = text.find(END, start + len(START)) if start != -1 else -1
    if start == -1 or end == -1:
        return None
    newline = "\r\n" if "\r\n" in text else "\n"
    body = block.replace("\n", newline)
    return text[: start + len(START)] + newline + body + newline + text[end:]
