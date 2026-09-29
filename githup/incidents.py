"""Incident issues: open on down, comment and close on recovery.

Every incident issue carries the labels ``githup``, ``incident`` and the
monitor's slug. Issues with ``githup`` + ``incident`` that you open by hand
(for planned maintenance, say) show up on the status page too.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone

from .github import GitHub, GitHubError
from .probe import DOWN

BASE_LABELS = ("githup", "incident")
_MARKER = re.compile(r"<!--\s*githup:incident\s+slug=([a-z0-9-]+)")


def _when(ts: int) -> str:
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


def duration(seconds: int) -> str:
    seconds = max(0, int(seconds))
    if seconds < 60:
        return f"{seconds}s"
    minutes = seconds // 60
    if minutes < 60:
        return f"{minutes} min"
    hours, minutes = divmod(minutes, 60)
    if hours < 48:
        return f"{hours} h {minutes} min" if minutes else f"{hours} h"
    days, hours = divmod(hours, 24)
    return f"{days} d {hours} h" if hours else f"{days} d"


def _what(result) -> str:
    if result.code:
        return f"HTTP {result.code}"
    return result.error or "no response"


def open_body(monitor, result, show_url: bool) -> str:
    target = f" (<{monitor.url}>)" if show_url else ""
    return (
        f"**{monitor.name}**{target} is down.\n\n"
        f"- Response: {_what(result)}\n"
        f"- Response time: {result.ms} ms\n"
        f"- Detected: {_when(result.checked_at)}\n"
        f"- Attempts: {result.attempts}\n\n"
        "This incident was opened automatically by [GitHup](https://github.com/StuxGroup/GitHup) "
        "and will be closed when the monitor recovers.\n\n"
        f"<!-- githup:incident slug={monitor.slug} started={result.checked_at} -->\n"
    )


def recovery_body(monitor, result, opened_at: int | None) -> str:
    down_for = f" after {duration(result.checked_at - opened_at)}" if opened_at else ""
    return (
        f"**{monitor.name}** is back {result.status}{down_for}: HTTP {result.code} "
        f"in {result.ms} ms at {_when(result.checked_at)}."
    )


def sync(gh: GitHub, config, results, previous: dict[str, dict], log=print) -> dict[str, dict | None]:
    """Open/close issues for status changes.

    ``previous`` maps slug to the previous summary entry. Returns
    ``{slug: incident-or-None}`` for every probed monitor; an incident is
    ``{"number", "url", "opened"}``. API errors are logged, not raised, so a
    GitHub hiccup never loses check data.
    """
    labels_created = False
    out: dict[str, dict | None] = {}
    for r in results:
        monitor = config.monitor(r.slug)
        prev = (previous.get(r.slug) or {}).get("incident")
        out[r.slug] = prev
        show_url = monitor.show_url if monitor.show_url is not None else config.site.show_urls
        try:
            if r.status == DOWN and not prev:
                labels = [*BASE_LABELS, r.slug, *config.incidents.labels]
                existing = gh.issues(labels=list(BASE_LABELS) + [r.slug], state="open", per_page=1)
                if existing:
                    issue = existing[0]
                    log(f"{r.slug}: reusing open incident #{issue['number']}")
                else:
                    if not labels_created:
                        gh.ensure_label("githup", "3ba7ff", "Managed by GitHup")
                        gh.ensure_label("incident", "d73a4a", "A GitHup outage report")
                        labels_created = True
                    issue = gh.create_issue(f"{monitor.name} is down", open_body(monitor, r, show_url),
                                            labels, list(config.incidents.assignees))
                    log(f"{r.slug}: opened incident #{issue['number']}")
                out[r.slug] = {"number": issue["number"], "url": issue.get("html_url", ""),
                               "opened": r.checked_at}
            elif r.status != DOWN and prev:
                gh.comment(prev["number"], recovery_body(monitor, r, prev.get("opened")))
                gh.close_issue(prev["number"])
                log(f"{r.slug}: closed incident #{prev['number']}")
                out[r.slug] = None
        except GitHubError as exc:
            log(f"::warning::GitHup could not update the incident for {r.slug}: {exc}")
    return out


def _parse_ts(value: str | None) -> int | None:
    if not value:
        return None
    return int(datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc).timestamp())


def list_for_site(gh: GitHub, slugs: list[str], limit: int = 30) -> list[dict]:
    """Recent incident issues, newest first, in a page-friendly shape."""
    items = gh.issues(labels=list(BASE_LABELS), state="all", per_page=limit)
    out = []
    for issue in items:
        names = [lbl["name"] if isinstance(lbl, dict) else str(lbl) for lbl in issue.get("labels", [])]
        slug = next((s for s in slugs if s in names), None)
        if slug is None:
            m = _MARKER.search(issue.get("body") or "")
            slug = m.group(1) if m else None
        out.append({
            "number": issue["number"],
            "title": issue.get("title", ""),
            "url": issue.get("html_url", ""),
            "state": issue.get("state", "open"),
            "slug": slug,
            "opened": _parse_ts(issue.get("created_at")),
            "closed": _parse_ts(issue.get("closed_at")),
            "comments": issue.get("comments", 0),
        })
    return out
