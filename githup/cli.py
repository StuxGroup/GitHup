"""Command line entry point: ``python -m githup <mode> [options]``.

Modes: ``check``, ``site``, ``readme`` (used by the action) and ``demo``
(example data for local previews). Run ``python -m githup <mode> --help``.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

from . import __version__, config as cfg, demo, gitops, incidents, readme, site, stats
from .github import GitHub, GitHubError
from .probe import inconclusive, probe_all
from .store import Store


def _truthy(value: str | None) -> bool:
    return str(value or "").strip().lower() in ("1", "true", "yes", "on")


def _log(msg: str) -> None:
    print(msg, flush=True)


def _output(name: str, value: str) -> None:
    path = os.environ.get("GITHUB_OUTPUT")
    if path:
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(f"{name}={value}\n")


def _secrets() -> dict:
    raw = os.environ.get("GITHUP_SECRETS", "").strip()
    if not raw:
        return {}
    try:
        data = json.loads(raw)
    except ValueError:
        _log("::warning::GitHup: the 'secrets' input is not valid JSON; pass ${{ toJSON(secrets) }}")
        return {}
    return data if isinstance(data, dict) else {}


def _repo(args) -> str:
    return getattr(args, "repo", "") or os.environ.get("GITHUB_REPOSITORY", "")


def _token() -> str:
    return os.environ.get("GITHUP_TOKEN") or os.environ.get("GITHUB_TOKEN") or ""


def _load(path):
    """Load the config and surface its warnings (deprecated keys) in the log."""
    config = cfg.load(path)
    for warning in config.warnings:
        _log(f"::warning::GitHup: {warning}")
    return config


def _show(config, mon) -> bool:
    return mon.show_url if mon.show_url is not None else config.site.show_urls


def _site_url(config, repo: str) -> str:
    if config.site.cname:
        return f"https://{config.site.cname}/"
    if repo:
        # Sites deployed with Actions keep their custom domain in the Pages settings, not the
        # config, so ask GitHub before guessing the default github.io address.
        try:
            url = GitHub(repo, _token()).pages_url()
        except (GitHubError, ValueError):
            url = ""
        if url:
            return url if url.endswith("/") else url + "/"
        owner, name = repo.split("/", 1)
        return f"https://{owner.lower()}.github.io/" + ("" if name.lower() == f"{owner.lower()}.github.io" else f"{name}/")
    return ""


# --------------------------------------------------------------------------


class InputError(ValueError):
    """An invalid action input or CLI flag."""


MAX_REPEAT = 6
MIN_INTERVAL = 60

# Seams for the tests: a monotonic clock and a sleep that never really waits.
_clock = time.monotonic
_sleep = time.sleep
_wall = time.time

ON_TIME = 1.5  # the schedule counts as on time when the last check is younger than ON_TIME x repeat-interval


def _updated(summary: dict) -> int:
    value = summary.get("updated")
    return int(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else 0


def _latest_check(store, fetch: bool = False) -> int:
    """Time of the newest check we can see: the local summary and, with ``fetch``, the remote's."""
    best = _updated(store.read_summary())
    if fetch:
        try:
            rel = store.summary_path.resolve().relative_to(Path.cwd().resolve()).as_posix()
            branch = gitops.current_branch()
            if gitops.git("fetch", "--depth", "1", "origin", branch, check=False).returncode == 0:
                shown = gitops.git("show", f"FETCH_HEAD:./{rel}", check=False)
                if shown.returncode == 0:
                    best = max(best, _updated(json.loads(shown.stdout or "{}")))
        except (gitops.GitError, ValueError, OSError):
            pass
    return best


def _int_input(name: str, raw, default: int) -> int:
    text = str(default if raw is None else raw).strip()
    if text == "":
        return default
    try:
        return int(text)
    except ValueError:
        raise InputError(f"{name} must be a whole number, got {text!r}") from None


def _repeat_settings(args) -> tuple[int, int]:
    repeat = _int_input("repeat", args.repeat, 1)
    interval = _int_input("repeat-interval", args.repeat_interval, 300)
    if not 1 <= repeat <= MAX_REPEAT:
        raise InputError(f"repeat must be between 1 and {MAX_REPEAT}, got {repeat}")
    if interval < MIN_INTERVAL:
        raise InputError(f"repeat-interval must be at least {MIN_INTERVAL} seconds, got {interval}")
    return repeat, interval


def cmd_check(args) -> int:
    repeat, interval = _repeat_settings(args)
    fill_gaps = bool(args.fill_gaps)
    if repeat > 1 and not fill_gaps:
        _log(f"::notice::GitHup: repeat: {repeat} is ignored because fill-gaps is off; "
             "set fill-gaps: true to check more than once when the schedule runs late.")
        repeat = 1
    if args.dry_run and repeat > 1:
        _log(f"[dry-run] running one round instead of {repeat}.")
        repeat = 1
    config = _load(args.config)
    store = Store(args.data_dir)

    last = _updated(store.read_summary())
    age = _wall() - last if last else None
    overdue = age is not None and age >= ON_TIME * interval
    if repeat > 1:
        if overdue or age is None:
            how = "no earlier check" if age is None else f"last check {incidents.duration(int(age))} ago"
            _log(f"::notice::GitHup: {how}: filling the gap, up to {repeat} rounds")
        else:
            _log("::notice::GitHup: schedule on time: 1 round")
            repeat = 1
    elif overdue:
        _log(f"::warning::GitHup: The last check was {incidents.duration(int(age))} ago: GitHub delayed this "
             "scheduled run. GitHub runs frequent schedules on a best-effort basis; "
             "see the fill-gaps input in the GitHup README.")

    started = _clock()
    changed = False
    push_failed = 0
    skipped_any = False
    summary: dict = {}
    entries: list = []
    rounds = 0
    for n in range(1, repeat + 1):
        if n > 1:
            wait = max(0.0, started + (n - 1) * interval - _clock())
            _log(f"Waiting {wait:.0f}s until the next round.")
            _sleep(wait)
            newest = _latest_check(store, fetch=args.commit and args.push)
            if newest > summary["updated"]:
                _log(f"A newer check landed ({incidents.duration(max(0, _wall() - newest))} ago): "
                     f"stopping after {rounds} round(s).")
                break
        if repeat > 1:
            _log(f"round {n}/{repeat}")
        round_changed, summary, entries, skipped, pushed_ok = _check_round(args, config, store, first=(n == 1))
        rounds += 1
        changed = changed or round_changed
        skipped_any = skipped_any or bool(skipped)
        if not pushed_ok:
            push_failed += 1

    if args.dry_run:
        return 1 if skipped_any else 0
    _output("status-changed", "true" if changed else "false")
    _output("status", summary["status"])
    _output("down", ",".join(e["slug"] for e in entries if e["status"] == "down"))
    if push_failed:
        _log(f"::error::GitHup: {push_failed} of {rounds} round(s) could not be pushed.")
        return 3
    return 1 if skipped_any else 0


def _check_round(args, config, store, first: bool):
    """One full round. Returns (status changed, summary, entries, skipped, push ok)."""
    previous = stats.summary_index(store.read_summary())
    results, skipped = probe_all(config.monitors, secrets=_secrets())
    for slug, err in skipped.items():
        _log(f"::error::GitHup: skipped {slug}: {err}")
    now = int(_wall())

    # Most monitors refused with the same 401/403/407/429: the runner is being blocked, not the sites
    # down. Hold those results back (no data, no incidents, status unchanged) - see probe.inconclusive.
    held = inconclusive(results, {slug: m.get("checked_at") for slug, m in previous.items()}, now)

    _log(f"{'monitor':<20} {'status':<9} {'code':>4} {'ms':>6}  tries  note")
    for r in results:
        note = f"{r.error} (inconclusive, not recorded)" if r.slug in held else r.error
        _log(f"{r.slug:<20} {r.status:<9} {r.code:>4} {r.ms:>6}  {r.attempts:>5}  {note}")
    if held:
        _log(f"::warning::GitHup: {len(held)} of {len(results)} monitors were refused with the same status code, "
             f"so this runner is probably being blocked; not recording them this round: {', '.join(sorted(held))}")
        results = [r for r in results if r.slug not in held]
    by_slug = {r.slug: r for r in results}

    changes = []
    for mon in config.monitors:
        r = by_slug.get(mon.slug)
        before = (previous.get(mon.slug) or {}).get("status")
        if r and before != r.status and (before is not None or r.status != "up"):
            changes.append((mon.slug, before, r))

    if args.dry_run:
        for slug, before, r in changes:
            _log(f"[dry-run] {slug}: {before or 'new'} -> {r.status}")
        _log("[dry-run] no data written, no issues touched, nothing committed.")
        return False, {}, [], skipped, True

    entries = []
    for mon in config.monitors:
        prev = previous.get(mon.slug)
        r = by_slug.get(mon.slug)
        if r:
            store.append(mon.slug, [r.as_check()])
        if prev and prev.get("totals"):
            totals = stats.add_totals(prev["totals"], [r.as_check()] if r else [])
        else:  # first run for this monitor, or a lost summary: rebuild from disk
            totals = stats.add_totals(None, store.load(mon.slug))
        recent = store.load(mon.slug, since=now - stats.WINDOWS["90d"] - 60)
        entries.append(stats.monitor_summary(mon, recent, totals, prev, now, _show(config, mon)))
        store.prune(mon.slug, config.keep_months, now)

    repo, token = _repo(args), _token()
    if config.incidents.enabled and not args.no_issues and results:
        if repo and token:
            try:
                gh = GitHub(repo, token)
                synced = incidents.sync(gh, config, results, previous, log=_log)
                for e in entries:
                    if e["slug"] in synced:
                        e["incident"] = synced[e["slug"]]
            except (GitHubError, ValueError) as exc:
                _log(f"::warning::GitHup: incidents skipped: {exc}")
        else:
            _log("Incidents: skipped (no GITHUB_REPOSITORY / token).")

    summary = stats.build_summary(config, entries, now)
    store.write_summary(summary)

    if changes:
        parts = [f"{slug} is {r.status} ({r.code if r.code else 'no response'})" for slug, _, r in changes]
        message = "GitHup: " + ", ".join(parts)
    else:
        message = "GitHup: update data"
    pushed_ok = True
    if args.commit:
        try:
            gitops.commit_and_push([str(store.root)], message, push=args.push, log=_log)
        except gitops.GitError as exc:
            _log(f"::error::GitHup git error: {exc}")
            pushed_ok = False
    else:
        _log(f"Not committing (would be: {message!r}).")

    first_run = first and not previous
    return bool(changes or first_run), summary, entries, skipped, pushed_ok


def cmd_site(args) -> int:
    config = _load(args.config)
    store = Store(args.data_dir)
    now = int(time.time())
    dev_mode = args.dev if args.dev is not None else _truthy(os.environ.get("DEV_MODE"))
    repo = _repo(args)
    slugs = [m.slug for m in config.monitors]

    found: list[dict] = []
    if args.incidents_file:
        found = json.loads(Path(args.incidents_file).read_text(encoding="utf-8"))
    elif not args.no_issues and repo:
        try:
            found = incidents.list_for_site(GitHub(repo, _token()), slugs)
        except (GitHubError, ValueError) as exc:
            _log(f"::warning::GitHup: could not load incidents: {exc}")

    live = ""
    if config.site.live_data and repo and not dev_mode:
        branch = args.data_branch or os.environ.get("GITHUB_REF_NAME") or ""
        if not branch:
            try:
                branch = gitops.current_branch()
            except gitops.GitError:
                branch = ""
        try:  # only data that lives inside the repo can be read from raw.githubusercontent.com
            rel = Path(args.data_dir).resolve().relative_to(Path.cwd().resolve()).as_posix()
        except ValueError:
            rel = ""
        if branch and rel:
            live = f"https://raw.githubusercontent.com/{repo}/{branch}/{rel}/summary.json"

    out = site.build(config, store, args.out, now=now, incidents=found, dev_mode=dev_mode, live_url=live, log=_log)
    _log(f"Built {out / 'index.html'} ({len(found)} incidents, {'dev' if dev_mode else 'production'} mode)")
    if args.dry_run or not args.deploy:
        _log("Not deploying (dry run / --no-deploy).")
        return 0
    gitops.deploy(out, branch=args.branch, cname=config.site.cname, log=_log)
    return 0


def cmd_readme(args) -> int:
    config = _load(args.config)
    store = Store(args.data_dir)
    path = Path(args.readme)
    if not path.is_file():
        _log(f"::warning::GitHup: {path} not found; skipping the README table.")
        return 0
    text = path.read_text(encoding="utf-8")
    site_url = args.site_url or _site_url(config, _repo(args))
    block = readme.table(config, store.read_summary(), site_url)
    new = readme.update(text, block)
    if new is None:
        _log(f"::warning::GitHup: add '{readme.START}' and '{readme.END}' to {path} to get a status table.")
        return 0
    if new == text:
        _log("README table is already up to date.")
        return 0
    if args.dry_run:
        _log(block)
        _log("[dry-run] README not written.")
        return 0
    path.write_bytes(new.encode("utf-8"))
    _log(f"Updated the status table in {path}.")
    if args.commit:
        gitops.commit_and_push([str(path)], "GitHup: update README", push=args.push, log=_log)
    return 0


def cmd_demo(args) -> int:
    config = _load(args.config)
    items = demo.generate(config, args.data_dir, int(time.time()), days=args.days)
    _log(f"Wrote example data for {len(config.monitors)} monitors to {args.data_dir} ({len(items)} incidents).")
    return 0


# --------------------------------------------------------------------------


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="githup", description="GitHup uptime monitor and status page.")
    p.add_argument("--version", action="version", version=f"GitHup {__version__}")
    sub = p.add_subparsers(dest="mode", required=True)

    def common(sp, commits: bool = True):
        sp.add_argument("--config", default=os.environ.get("GITHUP_CONFIG") or None,
                        help="config file (default: .githup.yml, .githup.yaml or .githup.json)")
        sp.add_argument("--data-dir", default=os.environ.get("GITHUP_DATA_DIR") or "data")
        sp.add_argument("--repo", default="", help="owner/name (default: $GITHUB_REPOSITORY)")
        sp.add_argument("--dry-run", action="store_true", help="change nothing: no writes, commits, issues or deploys")
        if commits:
            sp.add_argument("--no-commit", dest="commit", action="store_false", help="write files but do not commit")
            sp.add_argument("--no-push", dest="push", action="store_false", help="commit but do not push")

    c = sub.add_parser("check", help="probe every monitor and record the results")
    common(c)
    c.add_argument("--no-issues", action="store_true", help="do not open or close incident issues")
    c.add_argument("--repeat", default=os.environ.get("GITHUP_REPEAT") or None,
                   help=f"checks in a run that fills a gap, 1-{MAX_REPEAT} (default: 1; needs --fill-gaps)")
    c.add_argument("--fill-gaps", action="store_true", default=_truthy(os.environ.get("GITHUP_FILL_GAPS")),
                   help="when the last check is overdue, check up to --repeat times (default: off)")
    c.add_argument("--repeat-interval", default=os.environ.get("GITHUP_REPEAT_INTERVAL") or None,
                   help=f"seconds between checks, at least {MIN_INTERVAL} (default: 300)")
    c.set_defaults(func=cmd_check)

    s = sub.add_parser("site", help="build the status page and publish it to gh-pages")
    common(s, commits=False)
    s.add_argument("--out", default="_site", help="build directory (default: _site)")
    s.add_argument("--branch", default="gh-pages", help="Pages branch to publish to")
    s.add_argument("--data-branch", default="", help="branch that holds the data (for live refresh)")
    s.add_argument("--no-deploy", dest="deploy", action="store_false", help="build only")
    s.add_argument("--no-issues", action="store_true", help="do not read incidents from the Issues API")
    s.add_argument("--incidents-file", default="", help="read incidents from a JSON file instead of the API")
    s.add_argument("--dev", dest="dev", action="store_true", default=None, help="show the DEV MODE banner")
    s.add_argument("--no-dev", dest="dev", action="store_false", help="force production rendering")
    s.set_defaults(func=cmd_site)

    r = sub.add_parser("readme", help="update the status table between the githup markers in README.md")
    common(r)
    r.add_argument("--readme", default="README.md")
    r.add_argument("--site-url", default="", help="link the table to this status page instead of working it out")
    r.set_defaults(func=cmd_readme)

    d = sub.add_parser("demo", help="write synthetic example data (for local previews)")
    d.add_argument("--config", default="examples/.githup.yml")
    d.add_argument("--data-dir", default=".dev/data")
    d.add_argument("--days", type=int, default=90)
    d.set_defaults(func=cmd_demo)
    return p


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    args = parser().parse_args(argv)
    try:
        return args.func(args)
    except InputError as exc:
        _log(f"::error::GitHup input error: {exc}")
        return 2
    except cfg.ConfigError as exc:
        _log(f"::error::GitHup config error: {exc}")
        return 2
    except gitops.GitError as exc:
        _log(f"::error::GitHup git error: {exc}")
        return 3


if __name__ == "__main__":
    sys.exit(main())
