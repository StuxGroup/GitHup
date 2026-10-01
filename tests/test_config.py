import json
import unittest

from githup import config as cfg
from tests.helpers import EXAMPLE, TempDirCase


class ConfigTests(TempDirCase):
    def test_example_config_loads(self):
        c = cfg.load(EXAMPLE)
        self.assertEqual([m.slug for m in c.monitors], ["website", "api", "docs", "cdn"])
        api = c.monitor("api")
        self.assertEqual(api.expected, ((200, 200),))
        self.assertEqual(api.max_response_time, 1000)
        self.assertEqual(c.monitor("website").max_response_time, 3000)  # from defaults
        self.assertEqual(c.monitor("website").expected, cfg.DEFAULT_EXPECTED)
        self.assertEqual(c.monitor("cdn").expected, ((200, 299), (304, 304)))
        self.assertEqual(c.monitor("docs").method, "HEAD")
        self.assertEqual(c.site.accent, "#3ba7ff")
        self.assertEqual(c.legal.operator, "Example Ltd")
        self.assertEqual(c.legal.host, "GitHub Pages")
        self.assertEqual([g.slug for g in c.groups], ["platform", "assets"])
        self.assertEqual(c.group("platform").monitors, ("api", "docs"))
        self.assertTrue(c.group("assets").collapsed)
        self.assertEqual(c.monitor("website").group, "")
        self.assertEqual(c.monitor("cdn").group, "assets")
        self.assertEqual(c.monitor("docs").max_response_time, 3000)  # defaults reach grouped monitors

    def test_json_config(self):
        p = self.tmp / ".githup.json"
        p.write_text(json.dumps({"monitors": [{"name": "A B", "url": "https://a.test"}]}))
        c = cfg.load(p)
        self.assertEqual(c.monitors[0].slug, "a-b")
        self.assertEqual(c.site.name, "Status")

    def test_find(self):
        (self.tmp / ".githup.yml").write_text("monitors:\n  - name: x\n    url: https://x.test\n")
        self.assertEqual(cfg.find(self.tmp).name, ".githup.yml")
        with self.assertRaises(cfg.ConfigError):
            cfg.find(self.tmp / "missing")

    def test_expected_parsing(self):
        self.assertEqual(cfg.parse_expected([200, "301", "400-404", "5xx"], "t"),
                         ((200, 200), (301, 301), (400, 404), (500, 599)))
        for bad in ([], ["abc"], [700], [True], ["300-200"]):
            with self.subTest(bad=bad), self.assertRaises(cfg.ConfigError):
                cfg.parse_expected(bad, "t")

    def test_validation_errors(self):
        base = {"name": "x", "url": "https://x.test"}
        cases = [
            {"monitors": []},
            {"monitors": [{"url": "https://x.test"}]},
            {"monitors": [{"name": "x", "url": "ftp://x"}]},
            {"monitors": [base, base]},
            {"monitors": [{**base, "bogus": 1}]},
            {"monitors": [{**base, "method": "BREW"}]},
            {"monitors": [base], "site": {"accent": "purple"}},
            {"monitors": [base], "site": {"cname": "https://x.test"}},
            {"monitors": [base], "extra": 1},
            {"monitors": [{**base, "slug": "Bad Slug"}]},
            {"monitors": [{**base, "timeout": "10"}]},
        ]
        for data in cases:
            with self.subTest(data=data), self.assertRaises(cfg.ConfigError):
                cfg.parse(data)

    def test_groups(self):
        c = cfg.parse({"groups": [
            {"name": "Core Services", "description": "d", "monitors": [{"name": "A", "url": "https://a.test"}]},
            {"name": "Edge", "slug": "cdn", "collapsed": True, "monitors": [{"name": "B", "url": "https://b.test"}]},
        ]})
        self.assertEqual([(m.slug, m.group) for m in c.monitors], [("a", "core-services"), ("b", "cdn")])
        self.assertEqual(c.ungrouped(), ())
        self.assertEqual([(g.slug if g else None, [m.slug for m in ms]) for g, ms in c.sections()],
                         [("core-services", ["a"]), ("cdn", ["b"])])

    def test_group_validation_errors(self):
        base = {"name": "x", "url": "https://x.test"}
        cases = [
            {"groups": []},
            {"groups": [{"name": "G"}]},
            {"groups": [{"name": "G", "monitors": []}]},
            {"groups": [{"monitors": [base]}]},
            {"groups": [{"name": "G", "monitors": [base], "bogus": 1}]},
            {"groups": [{"name": "G", "slug": "Bad Slug", "monitors": [base]}]},
            {"groups": [{"name": "G", "collapsed": "yes", "monitors": [base]}]},
            {"groups": [{"name": "G", "monitors": [base]}, {"name": "G", "monitors": [{**base, "slug": "y"}]}]},
            {"monitors": [base], "groups": [{"name": "G", "monitors": [base]}]},  # slug clash across groups
            {"groups": {"name": "G"}},
        ]
        for data in cases:
            with self.subTest(data=data), self.assertRaises(cfg.ConfigError):
                cfg.parse(data)

    def test_headers_forms(self):
        c = cfg.parse({"monitors": [
            {"name": "a", "url": "https://a.test", "headers": {"X-A": "1"}},
            {"name": "b", "url": "https://b.test", "headers": ["X-B: 2", {"name": "X-C", "value": 3}]},
        ]})
        self.assertEqual(c.monitors[0].headers, (("X-A", "1"),))
        self.assertEqual(c.monitors[1].headers, (("X-B", "2"), ("X-C", "3")))

    def test_expand_placeholders(self):
        env = {"A": "env-a", "B": "env-b"}
        secrets = {"A": "secret-a"}
        self.assertEqual(cfg.expand("${{ secrets.A }}|${{ env.A }}|${B}", env, secrets), "secret-a|env-a|env-b")
        self.assertEqual(cfg.expand("${{ secrets.B }}", env, {}), "env-b")
        with self.assertRaises(KeyError):
            cfg.expand("${MISSING}", {}, {})
        self.assertEqual(cfg.placeholders("x ${A} ${{ secrets.B }}"), ["A", "B"])

    def test_short_hex_accent(self):
        c = cfg.parse({"monitors": [{"name": "x", "url": "https://x.test"}], "site": {"accent": "#AbC"}})
        self.assertEqual(c.site.accent, "#aabbcc")


if __name__ == "__main__":
    unittest.main()
