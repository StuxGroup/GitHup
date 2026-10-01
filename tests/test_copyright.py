import calendar
import unittest

from githup import config as cfg, site
from githup.store import Store
from tests.helpers import TempDirCase
from tests.test_site_readme import _Checker

MON = [{"name": "Web", "url": "https://example.com"}]
EN = "–"


def ts(year: int) -> int:
    """Mid-June of ``year`` as a UTC timestamp."""
    return calendar.timegm((year, 6, 15, 12, 0, 0))


def conf(copyright=None, legal=None, **site_keys):
    data = {"site": {"name": "Acme Status", "cname": "status.acme.test", **site_keys}, "monitors": MON}
    if copyright is not None:
        data["site"]["copyright"] = copyright
    if legal:
        data["legal"] = legal
    return cfg.parse(data)


def line(html: str) -> str:
    start = html.index('<p class="copyright">')
    return html[start:html.index("</p>", start) + 4]


class CopyrightConfigTests(unittest.TestCase):
    def test_block_is_optional(self):
        self.assertIsNone(conf().site.copyright)

    def test_holder_and_start(self):
        c = conf({"holder": "Acme <Ltd>", "start": 2019}).site.copyright
        self.assertEqual((c.holder, c.start), ("Acme <Ltd>", 2019))

    def test_start_is_optional_and_can_be_quoted(self):
        self.assertIsNone(conf({"holder": "Acme"}).site.copyright.start)
        self.assertEqual(conf({"holder": "Acme", "start": "2019"}).site.copyright.start, 2019)

    def test_validation(self):
        for bad in ("text", {"start": 2020}, {"holder": ""}, {"holder": "A", "start": 20}, {"holder": "A", "start": "soon"},
                    {"holder": "A", "start": 3500}, {"holder": "A", "start": True}, {"holder": "A", "since": 2020},
                    {"holder": ["A"]}):
            with self.assertRaises(cfg.ConfigError, msg=repr(bad)):
                conf(bad)

    def test_years(self):
        self.assertEqual(site.copyright_years(2026, 2026), "2026")
        self.assertEqual(site.copyright_years(None, 2026), "2026")
        self.assertEqual(site.copyright_years(2017, 2026), f"2017{EN}2026")
        self.assertEqual(site.copyright_years(2026, 2027), f"2026{EN}2027")
        self.assertEqual(site.copyright_years(2030, 2026), "2026")  # a future start never shows a backwards range


class CopyrightPageTests(TempDirCase):
    def render(self, c, year):
        return site.render(c, {}, {}, [], now=ts(year))

    def test_single_year_in_the_start_year(self):
        c = conf({"holder": "Stux.Group", "start": 2026})
        self.assertEqual(line(self.render(c, 2026)), '<p class="copyright">Copyright &copy; 2026 Stux.Group</p>')

    def test_range_after_the_start_year_and_rolls_over(self):
        c = conf({"holder": "Stux.Group", "start": 2026})
        self.assertIn(f"Copyright &copy; 2026{EN}2027 Stux.Group", self.render(c, 2027))
        self.assertIn(f"Copyright &copy; 2026{EN}2028 Stux.Group", self.render(c, 2028))

    def test_older_project(self):
        c = conf({"holder": "StuxieDev", "start": 2017})
        self.assertIn(f"Copyright &copy; 2017{EN}2026 StuxieDev", self.render(c, 2026))

    def test_holder_is_escaped(self):
        html = self.render(conf({"holder": "A & <B>", "start": 2026}), 2026)
        self.assertIn("2026 A &amp; &lt;B&gt;</p>", html)

    def test_no_block_no_line(self):
        self.assertNotIn('<p class="copyright">', self.render(conf(), 2026))

    def test_extra_pages_use_the_build_year(self):
        legal = {"operator": "Acme", "contact": "legal@acme.test"}
        c = conf({"holder": "Acme", "start": 2026}, legal=legal)
        store = Store(self.tmp / "data")
        out = site.build(c, store, self.tmp / "out", now=ts(2027))
        for rel in ("index.html", "404.html", "sitemap/index.html", "legal/index.html", "legal/privacy/index.html"):
            html = (out / rel).read_text(encoding="utf-8")
            self.assertIn(f"Copyright &copy; 2026{EN}2027 Acme", html, rel)
            checker = _Checker()
            checker.feed(html)


if __name__ == "__main__":
    unittest.main()
