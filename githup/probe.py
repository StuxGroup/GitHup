"""HTTP probing and status classification."""

from __future__ import annotations

import socket
import ssl
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Callable

from . import __version__
from .config import Monitor, expand

UP, DEGRADED, DOWN = "up", "degraded", "down"
USER_AGENT = f"GitHup/{__version__} (+https://github.com/StuxGroup/GitHup)"
MAX_BODY = 64 * 1024


@dataclass(frozen=True)
class Attempt:
    code: int  # 0 when no HTTP response was received
    ms: int
    error: str = ""


@dataclass(frozen=True)
class Result:
    slug: str
    status: str
    code: int
    ms: int
    checked_at: int
    attempts: int
    error: str = ""

    def as_check(self) -> list:
        return [self.checked_at, self.status, self.code, self.ms]


def code_ok(code: int, expected: tuple[tuple[int, int], ...]) -> bool:
    return any(lo <= code <= hi for lo, hi in expected)


def classify(code: int, ms: int, expected, max_response_time: int | None) -> str:
    """up / degraded / down for one attempt.

    A response whose code is not expected, or no response at all (code 0),
    is down. An expected response slower than ``max_response_time`` ms is
    degraded; otherwise it is up.
    """
    if code <= 0 or not code_ok(code, expected):
        return DOWN
    if max_response_time is not None and ms > max_response_time:
        return DEGRADED
    return UP


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: D401
        return None


def _opener(monitor: Monitor) -> urllib.request.OpenerDirector:
    handlers: list = []
    if not monitor.verify_tls:
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        handlers.append(urllib.request.HTTPSHandler(context=ctx))
    if not monitor.follow_redirects:
        handlers.append(_NoRedirect())
    return urllib.request.build_opener(*handlers)


def resolve(monitor: Monitor, env=None, secrets=None) -> tuple[str, dict[str, str], bytes | None]:
    """Expand placeholders in the URL, headers and body. Raises KeyError."""
    url = expand(monitor.url, env, secrets)
    headers = {"User-Agent": USER_AGENT, "Accept": "*/*"}
    for k, v in monitor.headers:
        headers[k] = expand(v, env, secrets)
    body = expand(monitor.body, env, secrets).encode("utf-8") if monitor.body is not None else None
    return url, headers, body


def fetch(monitor: Monitor, url: str, headers: dict[str, str], body: bytes | None) -> Attempt:
    """Make one real HTTP request and time it (headers plus up to 64 KiB of body)."""
    req = urllib.request.Request(url, data=body, headers=headers, method=monitor.method)
    start = time.perf_counter()
    try:
        with _opener(monitor).open(req, timeout=monitor.timeout) as resp:
            resp.read(MAX_BODY)
            code = resp.status
        return Attempt(code, _elapsed(start))
    except urllib.error.HTTPError as exc:
        try:
            exc.read(MAX_BODY)
        except Exception:  # noqa: BLE001 - body is irrelevant here
            pass
        finally:
            exc.close()
        return Attempt(exc.code, _elapsed(start), f"HTTP {exc.code}")
    except (socket.timeout, TimeoutError):
        return Attempt(0, _elapsed(start), f"timed out after {monitor.timeout:g}s")
    except urllib.error.URLError as exc:
        reason = exc.reason
        if isinstance(reason, (socket.timeout, TimeoutError)):
            return Attempt(0, _elapsed(start), f"timed out after {monitor.timeout:g}s")
        return Attempt(0, _elapsed(start), str(reason) or "connection failed")
    except (ssl.SSLError, ssl.CertificateError, ConnectionError, OSError) as exc:
        return Attempt(0, _elapsed(start), str(exc) or exc.__class__.__name__)
    except Exception as exc:  # noqa: BLE001 - never let one monitor crash the run
        return Attempt(0, _elapsed(start), f"{exc.__class__.__name__}: {exc}")


def _elapsed(start: float) -> int:
    return max(0, round((time.perf_counter() - start) * 1000))


Fetcher = Callable[[Monitor, str, dict, "bytes | None"], Attempt]


def probe(monitor: Monitor, *, env=None, secrets=None, fetcher: Fetcher = fetch,
          sleep: Callable[[float], None] = time.sleep, clock: Callable[[], float] = time.time) -> Result:
    """Probe a monitor, retrying while it looks down.

    Up to ``1 + retries`` attempts are made; the first attempt that is not
    down wins, so a single dropped connection does not count as an outage.
    """
    url, headers, body = resolve(monitor, env, secrets)
    checked_at = int(clock())
    attempts = 0
    attempt = Attempt(0, 0, "not probed")
    status = DOWN
    for attempts in range(1, monitor.retries + 2):
        attempt = fetcher(monitor, url, headers, body)
        status = classify(attempt.code, attempt.ms, monitor.expected, monitor.max_response_time)
        if status != DOWN:
            break
        if attempts <= monitor.retries and monitor.retry_delay:
            sleep(monitor.retry_delay)
    error = attempt.error if status == DOWN else ""
    if status == DOWN and not error:
        error = f"unexpected status {attempt.code}"
    return Result(monitor.slug, status, attempt.code, attempt.ms, checked_at, attempts, error)


# Codes a site sends when it refuses the client rather than failing itself.
BLOCK_CODES = (401, 403, 407, 429)
# How long a monitor's results can be held back as inconclusive before they count anyway.
INCONCLUSIVE_GRACE = 6 * 3600


def inconclusive(results, last_checked: dict, now: int) -> set:
    """Slugs whose down result this round should not be recorded.

    When most monitors in a round (more than half, and at least two) are down
    with the same blocking code (401, 403, 407 or 429), the checker itself is
    almost certainly being refused - typically a GitHub Actions runner whose
    address a CDN or host is blocking - and the sites are fine. Those results
    are held back instead of recorded as outages. Real outages (5xx, timeouts,
    refused connections) are never held back.

    ``last_checked`` maps slug to the time of its last recorded check. Once
    that is older than ``INCONCLUSIVE_GRACE``, the results count anyway, so a
    site that really does start refusing everyone still shows as down.
    """
    blocked = [r for r in results if r.status == DOWN and r.code in BLOCK_CODES]
    if not blocked:
        return set()
    counts: dict[int, int] = {}
    for r in blocked:
        counts[r.code] = counts.get(r.code, 0) + 1
    code = max(counts, key=counts.get)
    if counts[code] < 2 or counts[code] * 2 <= len(results):
        return set()
    return {r.slug for r in blocked
            if r.code == code and now - (last_checked.get(r.slug) or 0) < INCONCLUSIVE_GRACE}


def probe_all(monitors, *, env=None, secrets=None, fetcher: Fetcher = fetch, workers: int = 8,
              sleep=time.sleep, clock=time.time) -> tuple[list[Result], dict[str, str]]:
    """Probe monitors in parallel.

    Returns (results in config order, {slug: error}) where the second value
    lists monitors skipped because a placeholder could not be resolved.
    """
    skipped: dict[str, str] = {}
    runnable = []
    for m in monitors:
        try:
            resolve(m, env, secrets)
        except KeyError as exc:
            skipped[m.slug] = f"missing environment variable or secret {exc.args[0]}"
            continue
        runnable.append(m)
    if not runnable:
        return [], skipped
    with ThreadPoolExecutor(max_workers=max(1, min(workers, len(runnable)))) as pool:
        futures = [pool.submit(probe, m, env=env, secrets=secrets, fetcher=fetcher, sleep=sleep, clock=clock)
                   for m in runnable]
        return [f.result() for f in futures], skipped
