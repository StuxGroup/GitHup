import re
import unittest

from githup import config as cfg, site, stats
from githup.store import Store
from tests.helpers import TempDirCase
from tests.test_site_readme import _Checker

NOW = 1_790_000_000
MON = [{"name": "Web", "url": "https://example.com"}]
LEGAL = {"operator": "Acme", "contact": "legal@acme.test"}


def conf(kat=None, legal=True, **site_keys):
    data = {"site": {"name": "Acme Status", "cname": "status.acme.test", **site_keys}, "monitors": MON}
    if kat is not None:
        data["site"]["kat"] = kat
    if legal:
        data["legal"] = LEGAL
    return cfg.parse(data)


class CadenceTests(unittest.TestCase):
    def test_rounds_merge_monitors_and_average_gap(self):
        # three rounds 3 h apart; two monitors probed a few seconds apart in each round
        ts = [NOW - 6 * 3600, NOW - 6 * 3600 + 4, NOW - 3 * 3600, NOW - 3 * 3600 + 2, NOW, NOW - 1]
        c = stats.cadence(ts, NOW)
        self.assertEqual(c, {"window": 86400, "checks": 3, "every": 3 * 3600})

    def test_only_last_24h_and_too_little_data(self):
        self.assertEqual(stats.cadence([NOW - 90000], NOW)["checks"], 0)
        self.assertEqual(stats.cadence([NOW], NOW), {"window": 86400, "checks": 1, "every": None})
        self.assertEqual(stats.cadence([], NOW)["every"], None)

    def test_text(self):
        self.assertEqual(stats.cadence_text({"every": 300}), "checked about every 5 min (last 24 h)")
        self.assertEqual(stats.cadence_text({"every": 9590}), "checked about every 2 h 40 min (last 24 h)")
        self.assertEqual(stats.cadence_text({"every": 20}), "checked about every 1 min (last 24 h)")
        self.assertEqual(stats.cadence_text({"every": None}), "")
        self.assertEqual(stats.cadence_text(None), "")

    def test_summary_carries_cadence_only_when_given(self):
        c = conf()
        self.assertNotIn("cadence", stats.build_summary(c, [], NOW))
        self.assertEqual(stats.build_summary(c, [], NOW, [NOW - 600, NOW])["cadence"]["every"], 600)


class CadencePageTests(TempDirCase):
    def page(self, summary):
        store = Store(self.tmp / "data")
        store.write_summary(summary)
        out = site.build(conf(), store, self.tmp / "out", now=NOW)
        return (out / "index.html").read_text(encoding="utf-8")

    def test_shown_when_measured(self):
        html = self.page({"updated": NOW, "monitors": [], "cadence": {"window": 86400, "checks": 9, "every": 10800}})
        self.assertIn('<span id="cadence"> · <span class="cadence-text">checked about every 3 h (last 24 h)</span></span>', html)

    def test_hidden_without_data(self):
        html = self.page({"updated": NOW, "monitors": []})
        self.assertIn('<span id="cadence" hidden> · <span class="cadence-text"></span></span>', html)


class KatConfigTests(unittest.TestCase):
    def test_off_by_default_and_true_for_defaults(self):
        self.assertIsNone(conf().site.kat)
        self.assertIsNone(conf(False).site.kat)
        self.assertEqual(conf(True).site.kat, cfg.Kat())

    def test_options(self):
        k = conf({"kat": "Olly", "name": "cat", "picker": False}).site.kat
        self.assertEqual((k.kat, k.name, k.picker), ("olly", "cat", False))
        self.assertEqual(conf({"kat": "random"}).site.kat.kat, "random")

    def test_validation(self):
        for bad in ({"kat": "garfield"}, {"name": "<b>"}, {"nope": 1}, {"picker": "maybe"}, "yes", 3):
            with self.assertRaises(cfg.ConfigError, msg=bad):
                conf(bad)


class KatPageTests(TempDirCase):
    def build(self, c):
        return site.build(c, Store(self.tmp / "data"), self.tmp / "out", now=NOW)

    def pages(self, out):
        return ["index.html", "404.html", "sitemap/index.html", "legal/index.html", "legal/cookies/index.html"]

    def test_every_page_gets_script_picker_and_csp(self):
        out = self.build(conf({"kat": "olly", "name": "cat"}))
        for rel in self.pages(out):
            html = (out / rel).read_text(encoding="utf-8")
            chk = _Checker()
            chk.feed(html)
            self.assertEqual((chk.errors, chk.stack), ([], []), rel)
            self.assertEqual(chk.external, ["https://kat.stuxie.dev/kat.js"], rel)
            self.assertIn('<script src="https://kat.stuxie.dev/kat.js" data-kat="olly" data-name="cat" '
                          'data-z="800" defer></script>', html)
            self.assertIn('<p class="kat-picker" data-kat-picker-wrap hidden><label for="kat-picker">Your cat</label>'
                          '<select id="kat-picker" data-kat-picker>', html)
            self.assertIn('<option value="lily" title="In loving memory">Lily ✦</option>', html)
            self.assertIn('<option value="none">None</option>', html)
            csp = re.search(r'Content-Security-Policy" content="([^"]+)"', html).group(1)
            self.assertIn("script-src 'unsafe-inline' https://kat.stuxie.dev;", csp, rel)

    def test_defaults_pass_no_optional_attributes(self):
        html = (self.build(conf(True)) / "index.html").read_text(encoding="utf-8")
        self.assertIn('<script src="https://kat.stuxie.dev/kat.js" data-z="800" defer></script>', html)
        self.assertIn('<label for="kat-picker">Your kat</label>', html)

    def test_no_picker(self):
        html = (self.build(conf({"picker": False})) / "index.html").read_text(encoding="utf-8")
        self.assertIn("kat.stuxie.dev/kat.js", html)
        self.assertNotIn("kat-picker\" data-kat-picker-wrap", html)

    def test_off_means_nothing(self):
        out = self.build(conf())
        for rel in self.pages(out):
            html = (out / rel).read_text(encoding="utf-8")
            self.assertNotIn("kat.stuxie.dev", html, rel)
            self.assertNotIn("data-kat-picker", html, rel)
        self.assertNotIn("sdKat", (out / "legal/cookies/index.html").read_text(encoding="utf-8"))

    def test_legal_texts_mention_it(self):
        out = self.build(conf(True))
        self.assertIn("sdKat", (out / "legal/cookies/index.html").read_text(encoding="utf-8"))
        self.assertIn("kat.stuxie.dev", (out / "legal/privacy/index.html").read_text(encoding="utf-8"))
        out2 = site.build(conf({"picker": False}), Store(self.tmp / "data"), self.tmp / "out2", now=NOW)
        self.assertNotIn("sdKat", (out2 / "legal/cookies/index.html").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
