"""Generate believable example data for local previews (dev-server).

Nothing here touches the network: it writes 90 days of synthetic checks for
the monitors in a config, a matching summary.json and a list of fake
incidents, so the status page can be previewed with every state on show.
"""

from __future__ import annotations

import json
import random
import shutil
from pathlib import Path

from . import stats
from .probe import DEGRADED, DOWN, UP
from .store import Store

STEP = 600  # one synthetic check every 10 minutes


def _plan(index: int, now: int) -> list[tuple[int, int, str]]:
    """(start, end, status) windows that override the healthy default."""
    day = 86400
    plans = [
        [],
        [(now - 12 * day, now - 12 * day + 2 * 3600, DOWN), (now - 40 * day, now - 40 * day + 1800, DOWN)],
        [(now - 3 * day, now - 3 * day + 5 * 3600, DEGRADED), (now - 5400, now + 60, DEGRADED)],
        [(now - 61 * day, now - 60 * day, DOWN), (now - 20 * day, now - 20 * day + 3 * 3600, DEGRADED),
         (now - 2400, now + 60, DOWN)],
    ]
    return plans[index % len(plans)]


def generate(config, data_dir: str | Path, now: int, days: int = 90, seed: int = 7) -> list[dict]:
    rng = random.Random(seed)
    if Path(data_dir).exists():  # always start from a clean slate
        shutil.rmtree(data_dir)
    store = Store(data_dir)
    entries, incidents = [], []
    number = 100
    start = now - days * 86400
    start -= start % STEP
    for i, mon in enumerate(config.monitors):
        base = 90 + 70 * (i % 4)
        windows = _plan(i, now)
        checks = []
        for t in range(start, now + 1, STEP):
            status = UP
            for ws, we, st in windows:
                if ws <= t < we:
                    status = st
            if status == UP and rng.random() < 0.0004:
                status = DOWN
            ms = max(20, int(rng.gauss(base, base * 0.18)))
            code = 200
            if status == DEGRADED:
                ms = int(ms * rng.uniform(4, 7))
            if status == DOWN:
                code, ms = rng.choice([(503, 80), (502, 60), (0, int(mon.timeout * 1000))])
            checks.append([t, status, code, ms])
        store.append(mon.slug, checks)
        totals = stats.add_totals(None, checks)
        entries.append(stats.monitor_summary(mon, checks, totals, None, now,
                                             mon.show_url if mon.show_url is not None else config.site.show_urls))
        for ws, we, st in windows:
            if st != DOWN:
                continue
            number += 1
            ongoing = we > now
            incidents.append({
                "number": number, "title": f"{mon.name} is down", "url": f"https://github.com/example/status/issues/{number}",
                "state": "open" if ongoing else "closed", "slug": mon.slug, "opened": ws,
                "closed": None if ongoing else we, "comments": 0 if ongoing else 1,
            })
    store.write_summary(stats.build_summary(config, entries, now))
    incidents.sort(key=lambda x: x["opened"], reverse=True)
    (Path(data_dir) / "incidents.json").write_text(json.dumps(incidents, indent=1) + "\n", encoding="utf-8")
    return incidents
