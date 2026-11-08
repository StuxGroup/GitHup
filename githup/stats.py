"""Uptime maths, daily history bars, response-time series and the summary.

Uptime is check-based: ``available / total * 100`` where a check counts as
available when it is ``up`` or ``degraded`` (the service answered correctly,
just slowly). Average response times only use available checks, because a
down check's time is usually a timeout rather than a real response.
"""

from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone

from .incidents import duration
from .probe import DEGRADED, DOWN, UP

DAY = 86400
WINDOWS = {"24h": DAY, "7d": 7 * DAY, "30d": 30 * DAY, "90d": 90 * DAY}
SUMMARY_VERSION = 1


def available(status: str) -> bool:
    return status in (UP, DEGRADED)


def uptime(checks) -> float | None:
    """Percentage of available checks, or None when there are none."""
    total = len(checks)
    if not total:
        return None
    ok = sum(1 for c in checks if available(c[1]))
    return ok * 100.0 / total


def avg_ms(checks) -> int | None:
    times = [c[3] for c in checks if available(c[1])]
    return round(sum(times) / len(times)) if times else None


def floor_pct(value: float | None, places: int = 2) -> float | None:
    """Round *down*, so 99.999% is shown as 99.99% and never as 100.00%."""
    if value is None:
        return None
    f = 10 ** places
    return math.floor(value * f + 1e-9) / f


def fmt_pct(value: float | None, places: int = 2) -> str:
    v = floor_pct(value, places)
    return "n/a" if v is None else f"{v:.{places}f}%"


def window(checks, now: int, seconds: int) -> list:
    since = now - seconds
    return [c for c in checks if since < c[0] <= now]


# -- all-time totals, kept incrementally in the summary ---------------------


def empty_totals() -> dict:
    return {"checks": 0, "available": 0, "ms_sum": 0, "ms_n": 0, "first": None}


def add_totals(totals: dict | None, checks) -> dict:
    t = {**empty_totals(), **(totals or {})}
    for c in checks:
        t["checks"] += 1
        if available(c[1]):
            t["available"] += 1
            t["ms_sum"] += int(c[3])
            t["ms_n"] += 1
        if t["first"] is None or c[0] < t["first"]:
            t["first"] = int(c[0])
    return t


def totals_uptime(t: dict) -> float | None:
    return t["available"] * 100.0 / t["checks"] if t.get("checks") else None


def totals_avg(t: dict) -> int | None:
    return round(t["ms_sum"] / t["ms_n"]) if t.get("ms_n") else None


# -- page data ---------------------------------------------------------------


def day_level(day_uptime: float | None, degraded: int, checks: int) -> str:
    """Colour bucket for one day: none / ok / degraded / minor / major."""
    if day_uptime is None or checks == 0:
        return "none"
    if day_uptime >= 99.9:
        return "degraded" if degraded * 4 >= checks else "ok"
    if day_uptime >= 95.0:
        return "minor"
    return "major"


def daily(checks, now: int, days: int = 90) -> list[dict]:
    """One entry per UTC day, oldest first, ending with today."""
    today = datetime.fromtimestamp(now, tz=timezone.utc).date()
    first = today - timedelta(days=days - 1)
    buckets: dict = {first + timedelta(days=i): [] for i in range(days)}
    for c in checks:
        d = datetime.fromtimestamp(c[0], tz=timezone.utc).date()
        if d in buckets:
            buckets[d].append(c)
    out = []
    for d, cs in buckets.items():
        u = uptime(cs)
        deg = sum(1 for c in cs if c[1] == DEGRADED)
        out.append({
            "date": d.isoformat(),
            "checks": len(cs),
            "down": sum(1 for c in cs if c[1] == DOWN),
            "degraded": deg,
            "uptime": u,
            "avg_ms": avg_ms(cs),
            "level": day_level(u, deg, len(cs)),
        })
    return out


def hourly_ms(checks, now: int, hours: int = 48) -> list[int | None]:
    """Average response time per hour for the last ``hours`` hours."""
    end = now - now % 3600 + 3600
    start = end - hours * 3600
    sums = [0] * hours
    counts = [0] * hours
    for c in checks:
        if start <= c[0] < end and available(c[1]):
            i = (c[0] - start) // 3600
            sums[i] += c[3]
            counts[i] += 1
    return [round(s / n) if n else None for s, n in zip(sums, counts)]


def overall(statuses: list[str]) -> str:
    """Combine monitor statuses into one page-level state."""
    known = [s for s in statuses if s in (UP, DEGRADED, DOWN)]
    if not known:
        return "unknown"
    downs = known.count(DOWN)
    if downs == len(known):
        return "down"
    if downs:
        return "partial"
    if DEGRADED in known:
        return "degraded"
    return "up"


OVERALL_TEXT = {
    "up": "All systems operational",
    "degraded": "Degraded performance",
    "partial": "Partial outage",
    "down": "Major outage",
    "unknown": "No data yet",
}
STATUS_TEXT = {UP: "Operational", DEGRADED: "Degraded", DOWN: "Down", None: "No data", "unknown": "No data"}


# -- summary -----------------------------------------------------------------


def monitor_summary(monitor, checks_90d, totals: dict, prev: dict | None, now: int, show_url: bool = True) -> dict:
    """Summary entry for one monitor. ``checks_90d`` must cover >= 90 days."""
    prev = prev or {}
    latest = checks_90d[-1] if checks_90d else None
    status = latest[1] if latest else None
    last_change = prev.get("last_change")
    if status is not None and prev.get("status") != status:
        last_change = {"at": int(latest[0]), "from": prev.get("status"), "to": status}
    up = {k: floor_pct(uptime(window(checks_90d, now, s)), 3) for k, s in WINDOWS.items()}
    up["all"] = floor_pct(totals_uptime(totals), 3)
    ms = {k: avg_ms(window(checks_90d, now, s)) for k, s in WINDOWS.items()}
    ms["all"] = totals_avg(totals)
    return {
        "slug": monitor.slug,
        "name": monitor.name,
        "url": monitor.url if show_url else "",
        "status": status,
        "code": int(latest[2]) if latest else None,
        "ms": int(latest[3]) if latest else None,
        "checked_at": int(latest[0]) if latest else None,
        "last_change": last_change,
        "uptime": up,
        "avg_ms": ms,
        "totals": totals,
        "incident": prev.get("incident"),
    }


ROUND_GAP = 60  # checks less than this many seconds apart belong to the same round


def cadence(timestamps, now: int, seconds: int = DAY) -> dict:
    """How often checks really ran in the last ``seconds`` (24 h by default).

    GitHub runs ``schedule:`` workflows best-effort, so a ``*/5`` cron can land only a few times a
    day. Measuring the real rhythm keeps the page honest. Every monitor is probed in the same round,
    so timestamps from all monitors are merged and a cluster closer than ``ROUND_GAP`` counts once.
    ``every`` is the average gap between rounds in seconds (None with fewer than two rounds).
    """
    ts = sorted(int(t) for t in timestamps if now - seconds < int(t) <= now)
    rounds: list[int] = []
    for t in ts:
        if not rounds or t - rounds[-1] >= ROUND_GAP:
            rounds.append(t)
    every = round((rounds[-1] - rounds[0]) / (len(rounds) - 1)) if len(rounds) > 1 else None
    return {"window": seconds, "checks": len(rounds), "every": every}


def cadence_text(c: dict | None) -> str:
    """``checked about every 2 h 40 min (last 24 h)``, or "" when there is not enough data."""
    if not c or not c.get("every"):
        return ""
    every = int(c["every"])
    every = max(60, round(every / 60) * 60)  # whole minutes
    if every >= 3600:
        every = round(every / 600) * 600  # 10-minute steps once it is hours
    return f"checked about every {duration(every)} (last 24 h)"


def build_summary(config, monitors: list[dict], now: int, timestamps=None) -> dict:
    out = {
        "version": SUMMARY_VERSION,
        "generator": "GitHup",
        "updated": now,
        "name": config.site.name,
        "status": overall([m["status"] for m in monitors]),
        "monitors": monitors,
    }
    if timestamps is not None:
        out["cadence"] = cadence(timestamps, now)
    return out


def summary_index(summary: dict) -> dict[str, dict]:
    return {m["slug"]: m for m in summary.get("monitors", []) if isinstance(m, dict) and "slug" in m}
