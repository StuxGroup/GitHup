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


class RepeatTests(CheckFlowTests):
    """`repeat` / `repeat-interval` with a fake clock and sleep (nothing really waits)."""

    def setUp(self):
        super().setUp()
        self.now = 1000.0
        self.sleeps = []
        self.script = []  # one statuses dict per round
        self.round = 0
        self.logs = []

        def sleep(s):
            self.sleeps.append(s)
            self.now += s

        self.patches = [mock.patch.object(cli, "_clock", lambda: self.now),
                        mock.patch.object(cli, "_sleep", sleep),
                        mock.patch.object(cli, "_wall", lambda: 1_790_000_000 + self.now),
                        mock.patch.object(cli, "probe_all", self.probe),
                        mock.patch.object(cli, "_log", self.logs.append)]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in self.patches:
            p.stop()
        super().tearDown()

    def probe(self, monitors, **kw):
        statuses = self.script[min(self.round, len(self.script) - 1)]
        self.round += 1
        self.now += 20  # a round takes 20s
        t = int(1_790_000_000 + self.now)
        return [Result(m.slug, statuses[m.slug], 503 if statuses[m.slug] == "down" else 200, 42, t, 1)
                for m in monitors], {}

    def go(self, *extra):
        return cli.main(["check", *extra])

    def outputs(self):
        return dict(l.split("=", 1) for l in self.out_file.read_text().splitlines())

    def test_default_is_one_round(self):
        self.script = [{"web": "up", "api": "up"}]
        self.assertEqual(self.go(), 0)
        self.assertEqual(self.round, 1)
        self.assertEqual(self.sleeps, [])
        self.assertFalse(any("round" in m for m in self.logs))

    def test_multiple_rounds_sleep_the_remainder(self):
        self.script = [{"web": "up", "api": "up"}]
        self.assertEqual(self.go("--fill-gaps", "--repeat", "3", "--repeat-interval", "120"), 0)
        self.assertEqual(self.round, 3)
        self.assertEqual(self.sleeps, [100.0, 100.0])  # 120s minus the 20s the round took, no drift
        self.assertIn("round 2/3", self.logs)
        self.assertEqual(len(self.log()), 4)  # init + one commit per round
        summary = json.loads((self.repo / "data" / "summary.json").read_text())
        self.assertEqual(summary["monitors"][0]["totals"]["checks"], 3)

    def test_slow_round_does_not_sleep_negative(self):
        self.script = [{"web": "up", "api": "up"}]
        orig = self.probe

        def slow(monitors, **kw):
            out = orig(monitors, **kw)
            self.now += 500
            return out
        with mock.patch.object(cli, "probe_all", slow):
            self.go("--fill-gaps", "--repeat", "2", "--repeat-interval", "60")
        self.assertEqual(self.sleeps, [0.0])

    def test_status_changed_if_any_round_changed_and_last_round_reported(self):
        self.script = [{"web": "up", "api": "up"}]
        self.go()  # first run recorded
        self.now += 3 * 3600  # the schedule was late
        self.round, self.out_file.write_text("")
        self.script = [{"web": "up", "api": "up"}, {"web": "up", "api": "down"}, {"web": "up", "api": "up"}]
        self.go("--fill-gaps", "--repeat", "3", "--repeat-interval", "60")
        out = self.outputs()
        self.assertEqual(out["status-changed"], "true")
        self.assertEqual(out["status"], "up")  # last round
        self.assertEqual(out["down"], "")

    def test_status_changed_false_when_nothing_changed(self):
        self.script = [{"web": "up", "api": "up"}]
        self.go()
        self.now += 3 * 3600
        self.out_file.write_text("")
        self.go("--fill-gaps", "--repeat", "2", "--repeat-interval", "60")
        self.assertEqual(self.round, 3)
        self.assertEqual(self.outputs()["status-changed"], "false")

    def test_first_run_is_changed_even_when_later_rounds_are_not(self):
        self.script = [{"web": "up", "api": "up"}]
        self.go("--fill-gaps", "--repeat", "2", "--repeat-interval", "60")
        self.assertEqual(self.outputs()["status-changed"], "true")

    def test_fill_gaps_off_by_default_even_with_repeat(self):
        self.script = [{"web": "up", "api": "up"}]
        self.go()
        self.now += 2 * 3600
        self.logs.clear()
        self.assertEqual(self.go("--repeat", "4", "--repeat-interval", "300"), 0)
        self.assertEqual(self.round, 2)  # one more round only
        self.assertEqual(self.sleeps, [])
        self.assertTrue(any(m.startswith("::notice::") and "repeat: 4 is ignored" in m and "fill-gaps" in m
                            for m in self.logs))

    def test_overdue_warning_when_fill_gaps_is_off(self):
        self.script = [{"web": "up", "api": "up"}]
        self.go()
        self.now += 2 * 3600 + 14 * 60
        self.logs.clear()
        self.go()
        warn = [m for m in self.logs if m.startswith("::warning::")]
        self.assertEqual(len(warn), 1)
        self.assertIn("The last check was 2 h 14 min ago: GitHub delayed this scheduled run", warn[0])
        self.assertIn("fill-gaps input", warn[0])

    def test_no_warning_when_on_time_or_filling(self):
        self.script = [{"web": "up", "api": "up"}]
        self.go()
        self.now += 300
        self.logs.clear()
        self.go()
        self.assertFalse([m for m in self.logs if m.startswith("::warning::")])
        self.now += 2 * 3600
        self.logs.clear()
        self.go("--fill-gaps", "--repeat", "2", "--repeat-interval", "60")
        self.assertFalse([m for m in self.logs if m.startswith("::warning::")])

    def test_on_time_schedule_runs_one_round(self):
        self.script = [{"web": "up", "api": "up"}]
        self.go()
        self.now += 300  # the previous check was 5 minutes ago: GitHub is keeping up
        self.logs.clear()
        self.assertEqual(self.go("--fill-gaps", "--repeat", "4", "--repeat-interval", "300"), 0)
        self.assertEqual(self.round, 2)  # one more round only
        self.assertEqual(self.sleeps, [])
        self.assertTrue(any("schedule on time: 1 round" in m for m in self.logs))

    def test_just_over_the_threshold_fills_the_gap(self):
        self.script = [{"web": "up", "api": "up"}]
        self.go()
        self.now += 450  # exactly 1.5 x the interval since the last check was recorded
        self.logs.clear()
        self.go("--fill-gaps", "--repeat", "4", "--repeat-interval", "300")
        self.assertEqual(self.round, 5)
        self.assertTrue(any("filling the gap, up to 4 rounds" in m for m in self.logs))

    def test_overdue_runs_all_rounds(self):
        self.script = [{"web": "up", "api": "up"}]
        self.go()
        self.now += 2 * 3600
        self.logs.clear()
        self.assertEqual(self.go("--fill-gaps", "--repeat", "4", "--repeat-interval", "300"), 0)
        self.assertEqual(self.round, 5)
        self.assertEqual(self.sleeps, [280.0] * 3)
        self.assertTrue(any("last check 2 h" in m and "filling the gap, up to 4 rounds" in m for m in self.logs))
        self.assertIn("round 4/4", self.logs)

    def test_no_summary_yet_runs_all_rounds(self):
        self.script = [{"web": "up", "api": "up"}]
        self.go("--fill-gaps", "--repeat", "2", "--repeat-interval", "60")
        self.assertEqual(self.round, 2)

    def test_stops_early_when_a_newer_check_lands(self):
        self.script = [{"web": "up", "api": "up"}]
        self.go()
        self.now += 2 * 3600
        orig_sleep = cli._sleep

        def catch_up(seconds):  # another run catches up (pushes to the remote) while we wait for round 2
            orig_sleep(seconds)
            other = self.tmp / "other"
            _git("clone", "-b", "main", str(self.remote), str(other), cwd=self.tmp)
            summary = json.loads((other / "data" / "summary.json").read_text())
            summary["updated"] = int(1_790_000_000 + self.now + 100)
            (other / "data" / "summary.json").write_text(json.dumps(summary))
            _git("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-am", "other run", cwd=other)
            _git("push", "origin", "main", cwd=other)
        patcher = mock.patch.object(cli, "_sleep", catch_up)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.logs.clear()
        self.assertEqual(self.go("--fill-gaps", "--repeat", "4", "--repeat-interval", "300"), 0)
        self.assertEqual(self.round, 2)  # first run + round 1 here; rounds 2-4 skipped
        self.assertEqual(self.sleeps, [280.0])
        self.assertTrue(any("A newer check landed" in m and "stopping after 1 round(s)" in m for m in self.logs))
        self.assertNotIn("round 2/4", self.logs)

    def test_input_validation(self):
        self.script = [{"web": "up", "api": "up"}]
        for extra, text in ((("--fill-gaps", "--repeat", "0"), "between 1 and 6"), (("--fill-gaps", "--repeat", "7"), "between 1 and 6"),
                            (("--fill-gaps", "--repeat", "two"), "whole number"),
                            (("--repeat-interval", "59"), "at least 60"),
                            (("--repeat-interval", "soon"), "whole number")):
            self.logs.clear()
            self.assertEqual(self.go(*extra), 2, extra)
            self.assertTrue(any(text in m for m in self.logs), (extra, self.logs))
        self.assertEqual(self.round, 0)
        self.assertFalse((self.repo / "data").exists())

    def test_env_supplies_the_inputs(self):
        self.script = [{"web": "up", "api": "up"}]
        with mock.patch.dict(os.environ, {"GITHUP_FILL_GAPS": "true", "GITHUP_REPEAT": "2", "GITHUP_REPEAT_INTERVAL": "90"}):
            self.assertEqual(cli.main(["check"]), 0)
        self.assertEqual(self.round, 2)
        self.assertEqual(self.sleeps, [70.0])

    def test_dry_run_is_a_single_round(self):
        self.script = [{"web": "up", "api": "up"}]
        self.assertEqual(self.go("--fill-gaps", "--repeat", "3", "--dry-run"), 0)
        self.assertEqual(self.round, 1)
        self.assertEqual(self.sleeps, [])

    def test_push_failure_in_one_round_does_not_stop_the_rest(self):
        from githup import gitops
        self.script = [{"web": "up", "api": "up"}]
        real = gitops.commit_and_push
        calls = []

        def flaky(*a, **kw):
            calls.append(1)
            if len(calls) == 2:
                raise gitops.GitError("could not push to main after 4 attempts")
            return real(*a, **kw)
        with mock.patch.object(gitops, "commit_and_push", flaky):
            rc = self.go("--fill-gaps", "--repeat", "3", "--repeat-interval", "60")
        self.assertEqual(rc, 3)
        self.assertEqual(self.round, 3)  # all rounds ran
        self.assertEqual(len(calls), 3)
        self.assertTrue(any("1 of 3 round(s) could not be pushed" in m for m in self.logs))
        self.assertIn("status", self.outputs())


if __name__ == "__main__":
    unittest.main()
