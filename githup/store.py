"""On-disk data: one compact JSON file per monitor per UTC month.

Layout (relative to the data directory, ``data/`` by default)::

    summary.json              current state of every monitor
    <slug>/<YYYY-MM>.json     every check of that month

A month file looks like this, one check per line so git diffs stay small::

    {"monitor":"api","month":"2026-09","fields":["t","status","code","ms"],"checks":[
    [1790000000,"up",200,123],
    [1790000300,"down",503,88]
    ]}

``t`` is a Unix timestamp (UTC seconds), ``status`` is up/degraded/down,
``code`` is the HTTP status (0 when no response arrived) and ``ms`` is the
response time in milliseconds.
"""

from __future__ import annotations

import json
import os
import re
import tempfile
from datetime import datetime, timezone
from pathlib import Path

FIELDS = ["t", "status", "code", "ms"]
_MONTH = re.compile(r"^\d{4}-\d{2}$")

Check = list  # [t, status, code, ms]


def month_of(ts: int) -> str:
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m")


def _month_start(month: str) -> int:
    y, m = (int(p) for p in month.split("-"))
    return int(datetime(y, m, 1, tzinfo=timezone.utc).timestamp())


def _next_month(month: str) -> str:
    y, m = (int(p) for p in month.split("-"))
    return f"{y + (m == 12)}-{(m % 12) + 1:02d}"


def atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(text)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def dump_month(slug: str, month: str, checks: list[Check]) -> str:
    head = json.dumps({"monitor": slug, "month": month, "fields": FIELDS}, separators=(",", ":"))[:-1]
    rows = ",\n".join(json.dumps(c, separators=(",", ":")) for c in checks)
    return f'{head},"checks":[\n{rows}\n]}}\n' if rows else f'{head},"checks":[]}}\n'


class Store:
    def __init__(self, root: str | os.PathLike = "data"):
        self.root = Path(root)

    # -- month files -------------------------------------------------------

    def path(self, slug: str, month: str) -> Path:
        return self.root / slug / f"{month}.json"

    def months(self, slug: str) -> list[str]:
        d = self.root / slug
        if not d.is_dir():
            return []
        return sorted(p.stem for p in d.glob("*.json") if _MONTH.match(p.stem))

    def read_month(self, slug: str, month: str) -> list[Check]:
        p = self.path(slug, month)
        if not p.is_file():
            return []
        try:
            doc = json.loads(p.read_text(encoding="utf-8"))
        except ValueError as exc:
            raise ValueError(f"{p} is not valid JSON: {exc}") from exc
        return [list(c) for c in doc.get("checks", [])]

    def append(self, slug: str, checks: list[Check]) -> list[Path]:
        """Append checks, splitting them into the right month files."""
        by_month: dict[str, list[Check]] = {}
        for c in checks:
            by_month.setdefault(month_of(int(c[0])), []).append(list(c))
        written = []
        for month, new in sorted(by_month.items()):
            existing = self.read_month(slug, month)
            merged = existing + new
            merged.sort(key=lambda c: c[0])
            atomic_write(self.path(slug, month), dump_month(slug, month, merged))
            written.append(self.path(slug, month))
        return written

    def load(self, slug: str, since: int | None = None, until: int | None = None) -> list[Check]:
        """All checks with ``since <= t <= until``, oldest first."""
        out: list[Check] = []
        for month in self.months(slug):
            start = _month_start(month)
            end = _month_start(_next_month(month))
            if since is not None and end <= since:
                continue
            if until is not None and start > until:
                continue
            for c in self.read_month(slug, month):
                if (since is None or c[0] >= since) and (until is None or c[0] <= until):
                    out.append(c)
        out.sort(key=lambda c: c[0])
        return out

    def prune(self, slug: str, keep_months: int, now: int) -> list[Path]:
        """Delete month files older than the newest ``keep_months`` (0 keeps all)."""
        if keep_months <= 0:
            return []
        current = month_of(now)
        keep = [current]
        m = current
        for _ in range(keep_months - 1):
            y, mo = (int(p) for p in m.split("-"))
            m = f"{y - (mo == 1)}-{12 if mo == 1 else mo - 1:02d}"
            keep.append(m)
        removed = []
        for month in self.months(slug):
            if month < keep[-1]:
                p = self.path(slug, month)
                p.unlink()
                removed.append(p)
        return removed

    # -- summary -----------------------------------------------------------

    @property
    def summary_path(self) -> Path:
        return self.root / "summary.json"

    def read_summary(self) -> dict:
        p = self.summary_path
        if not p.is_file():
            return {}
        try:
            data = json.loads(p.read_text(encoding="utf-8") or "{}")
        except ValueError:
            return {}
        return data if isinstance(data, dict) else {}

    def write_summary(self, summary: dict) -> Path:
        atomic_write(self.summary_path, json.dumps(summary, indent=1, ensure_ascii=False) + "\n")
        return self.summary_path
