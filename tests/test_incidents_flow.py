import json
import os
import subprocess
import unittest
from unittest import mock

from githup import cli, incidents
from githup.github import GitHubError
from githup.probe import Result
from tests.helpers import TempDirCase, make_config


class FakeGitHub:
    def __init__(self, open_issues=None, fail=False):
        self.open_issues = open_issues or []
        self.calls = []
        self.fail = fail
        self.n = 40

    def issues(self, labels, state="open", per_page=30):
        self.calls.append(("issues", tuple(labels), state))
        if self.fail:
            raise GitHubError(500, "boom")
        return self.open_issues

    def ensure_label(self, name, color, description=""):
        self.calls.append(("label", name))

    def create_issue(self, title, body, labels, assignees=None):
        self.n += 1
        self.calls.append(("create", title, tuple(labels)))
        return {"number": self.n, "html_url": f"https://github.com/o/r/issues/{self.n}"}

    def comment(self, number, body):
        self.calls.append(("comment", number, body))

    def close_issue(self, number):
        self.calls.append(("close", number))


def result(slug, status, code=200, ms=50, t=1000):
    return Result(slug, status, code, ms, t, 1, "" if status != "down" else f"HTTP {code}")


class IncidentTests(unittest.TestCase):
    def setUp(self):
        self.c = make_config()

    def test_open_then_close(self):
        gh = FakeGitHub()
        out = incidents.sync(gh, self.c, [result("api", "down", 503), result("web", "up")], {}, log=lambda m: None)
        self.assertEqual(out["api"]["number"], 41)
        self.assertIsNone(out["web"])
        create = [c for c in gh.calls if c[0] == "create"][0]
        self.assertEqual(create[1], "API is down")
        self.assertEqual(create[2][:3], ("githup", "incident", "api"))

        gh2 = FakeGitHub()
        prev = {"api": {"status": "down", "incident": out["api"]}}
        out2 = incidents.sync(gh2, self.c, [result("api", "up", t=1000 + 1500)], prev, log=lambda m: None)
        self.assertIsNone(out2["api"])
        self.assertEqual([c[0] for c in gh2.calls], ["comment", "close"])
        self.assertIn("after 25 min", gh2.calls[0][2])

    def test_still_down_does_nothing(self):
        gh = FakeGitHub()
        prev = {"api": {"incident": {"number": 7, "opened": 1}}}
        out = incidents.sync(gh, self.c, [result("api", "down", 503)], prev, log=lambda m: None)
        self.assertEqual(out["api"]["number"], 7)
        self.assertEqual(gh.calls, [])

    def test_reuses_existing_open_issue(self):
        gh = FakeGitHub(open_issues=[{"number": 9, "html_url": "u"}])
        out = incidents.sync(gh, self.c, [result("api", "down", 0)], {}, log=lambda m: None)
        self.assertEqual(out["api"]["number"], 9)
        self.assertFalse(any(c[0] == "create" for c in gh.calls))

    def test_api_errors_are_logged_not_raised(self):
        logs = []
        out = incidents.sync(FakeGitHub(fail=True), self.c, [result("api", "down", 0)], {}, log=logs.append)
        self.assertIsNone(out["api"])
        self.assertTrue(any("::warning::" in m for m in logs))

    def test_duration(self):
        self.assertEqual(incidents.duration(30), "30s")
        self.assertEqual(incidents.duration(3600 * 3 + 120), "3 h 2 min")
        self.assertEqual(incidents.duration(86400 * 3), "3 d")


def _git(*args, cwd):
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True)


class CheckFlowTests(TempDirCase):
    """Runs `check` end to end against a throwaway git repo with a bare remote."""

    def setUp(self):
        super().setUp()
        self.remote = self.tmp / "remote.git"
        self.repo = self.tmp / "repo"
        _git("init", "--bare", "-b", "main", str(self.remote), cwd=self.tmp)
        _git("init", "-b", "main", str(self.repo), cwd=self.tmp)
        (self.repo / ".githup.json").write_text(json.dumps({
            "site": {"name": "T"}, "monitors": [{"name": "Web", "url": "https://example.com"},
                                                {"name": "API", "url": "https://api.example.com"}]}))
        _git("add", ".", cwd=self.repo)
        _git("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-m", "init", cwd=self.repo)
        _git("remote", "add", "origin", str(self.remote), cwd=self.repo)
        _git("push", "origin", "main", cwd=self.repo)
        self.cwd = os.getcwd()
        os.chdir(self.repo)
        self.out_file = self.tmp / "gh_output"
        self.env = mock.patch.dict(os.environ, {"GITHUB_OUTPUT": str(self.out_file), "GITHUB_REPOSITORY": "",
                                                "GITHUP_TOKEN": "", "GITHUB_TOKEN": ""})
        self.env.start()

    def tearDown(self):
        self.env.stop()
        os.chdir(self.cwd)
        super().tearDown()

    def run_check(self, statuses, *extra):
        self.t = getattr(self, "t", 1_790_000_000) + 300

        def fake(monitors, **kw):
            return [Result(m.slug, statuses[m.slug], 503 if statuses[m.slug] == "down" else 200, 42,
                           self.t, 1) for m in monitors], {}
        with mock.patch.object(cli, "probe_all", fake), mock.patch.object(cli, "_log", lambda m: None):
            return cli.main(["check", *extra])

    def log(self):
        r = subprocess.run(["git", "log", "--format=%s|%an", "main"], cwd=self.remote, capture_output=True, text=True)
        return r.stdout.strip().splitlines()

    def test_check_commits_and_reports_changes(self):
        self.assertEqual(self.run_check({"web": "up", "api": "up"}), 0)
        self.assertIn("status-changed=true", self.out_file.read_text())  # first run
        self.assertEqual(self.log()[0], "GitHup: update data|github-actions[bot]")
        self.assertEqual(self.run_check({"web": "up", "api": "down"}), 0)
        self.assertEqual(self.log()[0], "GitHup: api is down (503)|github-actions[bot]")
        summary = json.loads((self.repo / "data" / "summary.json").read_text())
        self.assertEqual(summary["status"], "partial")
        api = [m for m in summary["monitors"] if m["slug"] == "api"][0]
        self.assertEqual(api["totals"]["checks"], 2)
        self.assertEqual(api["uptime"]["all"], 50.0)
        self.assertTrue(self.out_file.read_text().strip().endswith("down=api"))

    def test_dry_run_writes_nothing(self):
        self.assertEqual(self.run_check({"web": "up", "api": "down"}, "--dry-run"), 0)
        self.assertFalse((self.repo / "data").exists())
        self.assertEqual(len(self.log()), 1)

    def test_deploy_to_gh_pages_keeps_cname(self):
        from githup import gitops
        site_dir = self.tmp / "site"
        site_dir.mkdir()
        (site_dir / "index.html").write_text("v1")
        self.assertTrue(gitops.deploy(site_dir, cname="status.example.com", log=lambda m: None))
        (site_dir / "index.html").write_text("v2")
        self.assertTrue(gitops.deploy(site_dir, log=lambda m: None))  # no cname in config: keep existing
        self.assertFalse(gitops.deploy(site_dir, log=lambda m: None))  # unchanged: no commit
        show = lambda f: subprocess.run(["git", "show", f"gh-pages:{f}"], cwd=self.remote,
                                        capture_output=True, text=True).stdout
        self.assertEqual(show("index.html"), "v2")
        self.assertEqual(show("CNAME").strip(), "status.example.com")
        branches = subprocess.run(["git", "branch", "--list"], cwd=self.repo, capture_output=True, text=True).stdout
        self.assertNotIn("githup-gh-pages", branches)


if __name__ == "__main__":
    unittest.main()
