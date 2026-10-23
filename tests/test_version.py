"""GitHup uses Date Versioning (https://datevers.ing): the UTC release date as YY.MM.DD, plus -1, -2... for later
releases the same day. No code reads CHANGELOG.md, so the changelog is checked here only for its headings."""

import re
import unittest
from datetime import datetime, timezone
from pathlib import Path

import githup

ROOT = Path(__file__).resolve().parent.parent
# The spec's own pattern (2000-2099 form); calendar validity is checked separately.
DATEVER = re.compile(r"^[0-9]{2}\.(0[1-9]|1[0-2])\.(0[1-9]|[12][0-9]|3[01])(-[1-9][0-9]*)?$")
SECTIONS = ["Added", "Changed", "Fixed", "Removed", "Security", "Deprecated"]


def version() -> str:
    return (ROOT / "VERSION.md").read_text(encoding="utf-8").strip()


class VersionTests(unittest.TestCase):
    def test_version_is_a_real_date_version(self):
        v = version()
        self.assertRegex(v, DATEVER)
        day = datetime.strptime(v.split("-")[0], "%y.%m.%d").replace(tzinfo=timezone.utc)  # raises on 30 Feb
        self.assertLessEqual(day.date(), datetime.now(timezone.utc).date(), "Date Versions are never in the future")

    def test_version_matches_version_md(self):
        self.assertEqual(version(), githup.__version__)

    def test_changelog_leads_with_the_current_version(self):
        text = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
        first = re.search(r"^## v(\S+)", text, re.M)
        self.assertEqual(first and first.group(1), version())

    def test_changelog_headings_are_date_versions_in_order(self):
        text = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
        entry = text.split("\n## v")[1]  # the newest entry
        found = re.findall(r"^### (\w+)", entry.split("\n## ")[0], re.M)
        self.assertTrue(found)
        self.assertEqual(found, sorted(found, key=SECTIONS.index))


if __name__ == "__main__":
    unittest.main()
