"""Committing data back and publishing the site to the Pages branch."""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from pathlib import Path

BOT_NAME = "github-actions[bot]"
BOT_EMAIL = "41898282+github-actions[bot]@users.noreply.github.com"
_IDENTITY = ["-c", f"user.name={BOT_NAME}", "-c", f"user.email={BOT_EMAIL}"]


class GitError(RuntimeError):
    pass


def git(*args: str, cwd: str | os.PathLike = ".", check: bool = True) -> subprocess.CompletedProcess:
    proc = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True)
    if check and proc.returncode != 0:
        raise GitError(f"git {' '.join(args)} failed: {proc.stderr.strip() or proc.stdout.strip()}")
    return proc


def current_branch(cwd=".") -> str:
    name = git("rev-parse", "--abbrev-ref", "HEAD", cwd=cwd).stdout.strip()
    if name == "HEAD":
        name = os.environ.get("GITHUB_REF_NAME", "")
    if not name:
        raise GitError("cannot tell which branch to push to (detached HEAD and no GITHUB_REF_NAME)")
    return name


def commit_and_push(paths: list[str], message: str, cwd=".", push: bool = True, attempts: int = 4,
                    log=print) -> bool:
    """Stage ``paths``, commit as github-actions[bot] and push, rebasing on conflict.

    Returns True when a commit was made.
    """
    existing = [p for p in paths if Path(cwd, p).exists()] or paths
    git("add", "-A", "--", *existing, cwd=cwd)
    if git("diff", "--cached", "--quiet", cwd=cwd, check=False).returncode == 0:
        log("No data changes to commit.")
        return False
    git(*_IDENTITY, "commit", "-m", message, cwd=cwd)
    log(f"Committed: {message}")
    if not push:
        return True
    branch = current_branch(cwd)
    for n in range(1, attempts + 1):
        if git("push", "origin", f"HEAD:refs/heads/{branch}", cwd=cwd, check=False).returncode == 0:
            log(f"Pushed to {branch}.")
            return True
        if n == attempts:
            break
        log(f"Push rejected, rebasing on origin/{branch} (attempt {n})")
        rebase = git(*_IDENTITY, "pull", "--rebase", "origin", branch, cwd=cwd, check=False)
        if rebase.returncode != 0:
            git("rebase", "--abort", cwd=cwd, check=False)
            raise GitError(f"could not rebase onto origin/{branch}: {rebase.stderr.strip()}")
    raise GitError(f"could not push to {branch} after {attempts} attempts")


def deploy(site_dir: str | os.PathLike, branch: str = "gh-pages", cwd=".", cname: str = "",
           message: str = "GitHup: publish status page", log=print) -> bool:
    """Replace the contents of ``branch`` with ``site_dir`` and push.

    Uses a temporary worktree so the main checkout is untouched. An existing
    CNAME on the branch is kept when the config does not set one, and Pages
    settings are never touched. Returns True when something was pushed.
    """
    site_dir = Path(site_dir).resolve()
    has_remote = git("fetch", "--depth", "1", "origin", branch, cwd=cwd, check=False).returncode == 0
    tmp = Path(tempfile.mkdtemp(prefix="githup-pages-"))
    wt = tmp / "wt"
    try:
        if has_remote:
            git("worktree", "add", "--detach", str(wt), "FETCH_HEAD", cwd=cwd)
        else:
            git("worktree", "add", "--detach", str(wt), "HEAD", cwd=cwd)
            git("checkout", "--orphan", f"githup-{branch}", cwd=wt)
            git("rm", "-rf", "--quiet", ".", cwd=wt)
        old_cname = (wt / "CNAME").read_text(encoding="utf-8").strip() if (wt / "CNAME").is_file() else ""
        for entry in wt.iterdir():
            if entry.name == ".git":
                continue
            shutil.rmtree(entry) if entry.is_dir() else entry.unlink()
        shutil.copytree(site_dir, wt, dirs_exist_ok=True)
        final_cname = cname or old_cname
        if final_cname:
            (wt / "CNAME").write_text(final_cname + "\n", encoding="utf-8")
        (wt / ".nojekyll").write_text("", encoding="utf-8")
        git("add", "-A", cwd=wt)
        if has_remote and git("diff", "--cached", "--quiet", cwd=wt, check=False).returncode == 0:
            log(f"{branch} is already up to date.")
            return False
        git(*_IDENTITY, "commit", "-m", message, cwd=wt)
        git("push", "origin", f"HEAD:refs/heads/{branch}", cwd=wt)
        log(f"Published the status page to {branch}.")
        return True
    finally:
        git("worktree", "remove", "--force", str(wt), cwd=cwd, check=False)
        shutil.rmtree(tmp, ignore_errors=True)
        if not has_remote:
            git("branch", "-D", f"githup-{branch}", cwd=cwd, check=False)
