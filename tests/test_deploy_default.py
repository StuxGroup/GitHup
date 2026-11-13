import os
from unittest import mock

from githup import cli, gitops
from tests.helpers import TempDirCase

CONFIG = """site:
  name: Deploy Test
monitors:
  - name: Web
    url: https://example.com
"""


class DeployDefaultTests(TempDirCase):
    """`githup site` publishes by default only inside GitHub Actions; by hand it needs --deploy."""

    def setUp(self):
        super().setUp()
        self.cfg = self.tmp / ".githup.yml"
        self.cfg.write_text(CONFIG, encoding="utf-8")
        self.logs = []

    def run_site(self, *extra, actions=None):
        env = {k: v for k, v in os.environ.items() if k not in ("GITHUB_ACTIONS", "GITHUB_REPOSITORY")}
        if actions is not None:
            env["GITHUB_ACTIONS"] = actions
        deploy = mock.MagicMock(return_value=True)
        with mock.patch.dict(os.environ, env, clear=True), mock.patch.object(gitops, "deploy", deploy), \
                mock.patch.object(cli, "_log", self.logs.append):
            code = cli.main(["site", "--config", str(self.cfg), "--data-dir", str(self.tmp / "data"),
                             "--out", str(self.tmp / "out"), "--no-issues", *extra])
        self.assertEqual(code, 0)
        self.assertTrue((self.tmp / "out" / "index.html").is_file())
        return deploy.called

    def test_by_hand_builds_only(self):
        self.assertFalse(self.run_site())
        self.assertTrue(any("not running in GitHub Actions" in m and "--deploy" in m for m in self.logs))

    def test_by_hand_deploys_with_flag(self):
        self.assertTrue(self.run_site("--deploy"))

    def test_actions_deploys_by_default(self):
        self.assertTrue(self.run_site(actions="true"))

    def test_no_deploy_wins_in_actions(self):
        self.assertFalse(self.run_site("--no-deploy", actions="true"))
        self.assertTrue(any("--no-deploy" in m for m in self.logs))

    def test_dry_run_never_deploys(self):
        self.assertFalse(self.run_site("--deploy", "--dry-run", actions="true"))
