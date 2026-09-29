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
from .probe import probe_all
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


def _show(config, mon) -> bool:
    return mon.show_url if mon.show_url is not None else config.site.show_urls


def _site_url(config, repo: str) -> str:
    if config.site.cname:
        return f"https://{config.site.cname}/"
    if repo:
        owner, name = repo.split("/", 1)
        return f"https://{owner.lower()}.github.io/" + ("" if name.lower() == f"{owner.lower()}.github.io" else f"{name}/")
    return ""


# --------------------------------------------------------------------------


def cmd_check(args) -> int:
    config = cfg.load(args.config)
    store = Store(args.data_dir)
    previous = stats.summary_index(store.read_summary())
    results, skipped = probe_all(config.monitors, secrets=_secrets())
    for slug, err in skipped.items():
        _log(f"::error::GitHup: skipped {slug}: {err}")
    by_slug = {r.slug: r for r in results}
    now = int(time.time())

    _log(f"{'monitor':<20} {'status':<9} {'code':>4} {'ms':>6}  tries  note")
    for mon in config.monitors:
        r = by_slug.get(mon.slug)
        if r:
            _log(f"{mon.slug:<20} {r.status:<9} {r.code:>4} {r.ms:>6}  {r.attempts:>5}  {r.error}")

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
        return 1 if skipped else 0

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
    if args.commit:
        gitops.commit_and_push([str(store.root)], message, push=args.push, log=_log)
    else:
        _log(f"Not committing (would be: {message!r}).")

    first_run = not previous
    _output("status-changed", "true" if (changes or first_run) else "false")
    _output("status", summary["status"])
    _output("down", ",".join(e["slug"] for e in entries if e["status"] == "down"))
    return 1 if skipped else 0


def cmd_site(args) -> int:
    config = cfg.load(args.config)
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

    out = site.build(config, store, args.out, now=now, incidents=found, dev_mode=dev_mode, live_url=live)
    _log(f"Built {out / 'index.html'} ({len(found)} incidents, {'dev' if dev_mode else 'production'} mode)")
    if args.dry_run or not args.deploy:
        _log("Not deploying (dry run / --no-deploy).")
        return 0
    gitops.deploy(out, branch=args.branch, cname=config.site.cname, log=_log)
    return 0


def cmd_readme(args) -> int:
    config = cfg.load(args.config)
    store = Store(args.data_dir)
    path = Path(args.readme)
    if not path.is_file():
        _log(f"::warning::GitHup: {path} not found; skipping the README table.")
        return 0
    text = path.read_text(encoding="utf-8")
    block = readme.table(config, store.read_summary(), _site_url(config, _repo(args)))
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
    config = cfg.load(args.config)
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
    except cfg.ConfigError as exc:
        _log(f"::error::GitHup config error: {exc}")
        return 2
    except gitops.GitError as exc:
        _log(f"::error::GitHup git error: {exc}")
        return 3


if __name__ == "__main__":
    sys.exit(main())
