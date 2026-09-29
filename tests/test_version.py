import unittest
from pathlib import Path

import githup

ROOT = Path(__file__).resolve().parent.parent


class VersionTests(unittest.TestCase):
    def test_version_matches_version_md(self):
        self.assertEqual((ROOT / "VERSION.md").read_text().strip(), githup.__version__)

    def test_changelog_has_current_version(self):
        self.assertIn(f"## v{githup.__version__}", (ROOT / "CHANGELOG.md").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
