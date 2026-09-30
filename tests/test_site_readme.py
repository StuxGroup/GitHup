import json
import re
import unittest
from html.parser import HTMLParser

import githup
from githup import config as cfg, demo, readme, site, stats
from githup.store import Store
from tests.helpers import EXAMPLE, TempDirCase, make_config

VOID = {"meta", "link", "img", "br", "hr", "input", "circle", "polyline", "polygon", "path", "source"}


class _Checker(HTMLParser):
    """Tracks tag balance, ids and external resources."""

    def __init__(self):
        super().__init__()
        self.stack, self.errors, self.ids, self.external = [], [], [], []

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if a.get("id"):
            self.ids.append(a["id"])
        if tag == "script" and a.get("src"):
            self.external.append(a["src"])
        if tag == "link" and a.get("rel") == "stylesheet":
            self.external.append(a.get("href"))
        if tag not in VOID:
            self.stack.append(tag)

    def handle_startendtag(self, tag, attrs):
        if dict(attrs).get("id"):
            self.ids.append(dict(attrs)["id"])

    def handle_endtag(self, tag):
        if tag in VOID:
            return
        if not self.stack or self.stack[-1] != tag:
            self.errors.append(f"unexpected </{tag}> (open: {self.stack[-3:]})")
            return
        self.stack.pop()


class SiteTests(TempDirCase):
    def build_demo(self, dev=True):
        c = cfg.load(EXAMPLE)
        now = 1_790_000_000
        inc = demo.generate(c, self.tmp / "data", now)
        out = site.build(c, Store(self.tmp / "data"), self.tmp / "site", now=now, incidents=inc, dev_mode=dev,
                         live_url="" if dev else "https://raw.githubusercontent.com/o/r/main/data/summary.json")
        return c, out, (out / "index.html").read_text(encoding="utf-8")

    def test_render_is_well_formed_and_self_contained(self):
        c, out, html = self.build_demo()
        chk = _Checker()
        chk.feed(html)
        self.assertEqual(chk.errors, [])
        self.assertEqual(chk.stack, [])
        self.assertEqual(len(chk.ids), len(set(chk.ids)), "duplicate ids")
        self.assertEqual(chk.external, [])
        for f in ("index.html", "summary.json", "404.html", "CNAME", ".nojekyll"):
            self.assertTrue((out / f).exists(), f)
        self.assertEqual((out / "CNAME").read_text().strip(), "status.example.com")
        json.loads((out / "summary.json").read_text())

    def test_content(self):
        c, out, html = self.build_demo()
        self.assertEqual(html.count('class="bar lvl-'), 90 * len(c.monitors))
        self.assertIn('<div class="site-banner site-banner--dev" role="note"><span class="site-banner-label">Dev mode</span>', html)
        self.assertIn('<html lang="en" class="has-site-banner">', html)
        self.assertIn("--banner-h", html)  # the shared banner CSS and JS are inlined
        self.assertIn("ResizeObserver", html)
        self.assertIn("URLSearchParams(location.search).get('banner')", html)  # dev-only preview
        self.assertIn('href="https://example.com/legal">Boring Legal Stuff</a>', html)
        self.assertIn('Powered by GitHup</a>', html)
        self.assertIn(f'/releases/tag/v{githup.__version__}">v{githup.__version__}</a>', html)
        self.assertIn('<a href="https://github.com/StuxGroup/GitHup"><svg class="gh-mark"', html)
        self.assertIn('<a href="https://services.stux.group">A Stux.Group Service</a>', html)
        self.assertIn("prefers-color-scheme: dark", html)
        self.assertIn('data-theme="dark"', html)
        self.assertIn("localStorage", html)
        self.assertIn('role="status"', html)
        self.assertIn("<svg", html)
        self.assertIn("Ongoing incidents", html)
        self.assertIn("Recent incidents", html)
        self.assertIn("--accent:#3ba7ff", html)
        # every coloured state also carries text
        for text in ("Operational", "Degraded", "Some downtime", "Major outage"):
            self.assertIn(text, html)

    def test_groups_render(self):
        c, out, html = self.build_demo()
        self.assertIn('id="g-platform" data-group="platform"', html)
        self.assertIn('<h3>Platform</h3><span class="group-count">2 monitors</span>', html)
        self.assertIn("The API and documentation behind the product.", html)
        self.assertIn("<h4>API</h4>", html)
        self.assertIn("<h3>Website</h3>", html)  # ungrouped monitors keep h3
        self.assertLess(html.index('id="m-website"'), html.index('id="g-platform"'))

    def test_collapsed_group_opens_on_outage(self):
        c = cfg.parse({"groups": [
            {"name": "Quiet", "collapsed": True, "monitors": [{"name": "A", "url": "https://a.test"}]},
            {"name": "Loud", "collapsed": True, "monitors": [{"name": "B", "url": "https://b.test"},
                                                             {"name": "C", "url": "https://c.test"}]},
        ]})
        summary = {"monitors": [{"slug": "a", "status": "up"}, {"slug": "b", "status": "down"},
                                {"slug": "c", "status": "up"}]}
        html = site.render(c, summary, {}, [], now=1_790_000_000)
        quiet = html[html.index('id="g-quiet"'):html.index('id="g-loud"')]
        loud = html[html.index('id="g-loud"'):]
        self.assertIn("<details>", quiet)
        self.assertIn("<details open>", loud)
        self.assertIn('class="group st-partial"', html)
        self.assertIn("Partial outage", loud)

    def test_no_groups_layout_unchanged(self):
        html = site.render(make_config(), {}, {}, [], now=1_790_000_000)
        self.assertNotIn('class="groups"', html)
        self.assertIn("<h3>Web</h3>", html)

    def test_production_mode(self):
        c, out, html = self.build_demo(dev=False)
        self.assertNotIn('class="site-banner site-banner--dev"', html)
        self.assertNotIn("--banner-h", html)  # no banner, so no banner CSS or JS
        self.assertNotIn('class="has-site-banner"', html)
        self.assertNotIn("URLSearchParams(location.search).get('banner')", html)
        self.assertIn("https://raw.githubusercontent.com/o/r/main/data/summary.json", html)
        self.assertIn("connect-src 'self' https://raw.githubusercontent.com", html)

    def test_site_notice_banner(self):
        c = make_config(notice="Planned maintenance on <Friday>")
        html = site.render(c, {}, {}, [], now=1_790_000_000)
        self.assertIn('<div class="site-banner site-banner--site" role="note"><span class="site-banner-label">Notice</span>'
                      '<span class="site-banner-text">Planned maintenance on &lt;Friday&gt;</span></div>', html)
        self.assertIn('<html lang="en" class="has-site-banner">', html)
        self.assertNotIn("get('banner')", html)  # the preview script is dev-only
        self.assertNotIn("site-banner--site", site.render(make_config(), {}, {}, [], now=1_790_000_000))

    def test_footer_is_muted_until_hovered(self):
        html = site.render(make_config(), {}, {}, [], now=1_790_000_000)
        self.assertIn(".gh-mark{width:20px;height:20px;flex:none;filter:grayscale(1) brightness(1);opacity:.7", html)
        self.assertIn("filter:grayscale(0) brightness(1);opacity:1", html)
        self.assertNotIn("filter:none", html)  # never transition to filter:none (hover glitch)
        self.assertIn(".powered a:hover .gh-mark", html)
        self.assertNotIn("Created with", html)
        self.assertNotIn("Stuxedo", html)

    def test_empty_data_renders(self):
        c = make_config()
        out = site.build(c, Store(self.tmp / "none"), self.tmp / "s", now=1_790_000_000)
        html = (out / "index.html").read_text(encoding="utf-8")
        self.assertIn("No data yet", html)
        self.assertIn("No incidents in the last 90 days", html)
        self.assertNotIn("CNAME", [p.name for p in out.iterdir()])

    def test_escaping(self):
        c = make_config(monitors=[{"name": "<b>x</b>", "url": "https://x.test/?a=1&b=2"}], name="A & <B>")
        html = site.render(c, {}, {}, [], now=1_790_000_000)
        self.assertNotIn("<b>x</b>", html)
        self.assertIn("A &amp; &lt;B&gt;", html)

    def test_accent_contrast(self):
        light = site.readable("#ffee00", "#ffffff")
        self.assertGreaterEqual(site.contrast(light, "#ffffff"), 4.5)
        dark = site.readable("#a349a4", "#161b22")
        self.assertGreaterEqual(site.contrast(dark, "#161b22"), 4.5)


class ReadmeTests(unittest.TestCase):
    def setUp(self):
        self.c = make_config()
        self.summary = {"status": "partial", "monitors": [
            {"slug": "web", "status": "up", "uptime": {"24h": 100.0, "7d": 99.5, "30d": 99.99}, "avg_ms": {"24h": 120}},
            {"slug": "api", "status": "down", "uptime": {"24h": 50.0, "7d": None, "30d": None}, "avg_ms": {"24h": None}},
        ]}

    def test_table(self):
        t = readme.table(self.c, self.summary, "https://status.example.com/")
        self.assertIn("**Partial outage** · [Live status page](https://status.example.com/)", t)
        self.assertIn("| [Web](https://example.com) | Up | 100.00% | 99.50% | 99.99% | 120 ms |", t)
        self.assertIn("| [API](https://api.example.com) | **Down** | 50.00% | n/a | n/a | n/a |", t)

    def test_table_with_groups(self):
        c = cfg.parse({"monitors": [{"name": "Web", "url": "https://example.com"}],
                       "groups": [{"name": "Back | end", "monitors": [{"name": "API", "url": "https://api.example.com"}]}]})
        t = readme.table(c, self.summary)
        self.assertIn("| Group | Monitor | Status |", t)
        self.assertIn("|  | [Web](https://example.com) | Up |", t)
        self.assertIn("| Back \\| end | [API](https://api.example.com) | **Down** |", t)

    def test_update_between_markers(self):
        text = f"# Hi\n\n{readme.START}\nold\n{readme.END}\n\nafter\n"
        new = readme.update(text, "NEW")
        self.assertEqual(new, f"# Hi\n\n{readme.START}\nNEW\n{readme.END}\n\nafter\n")
        self.assertEqual(readme.update(new, "NEW"), new)
        self.assertIsNone(readme.update("no markers", "x"))

    def test_crlf_preserved(self):
        text = f"a\r\n{readme.START}\r\n{readme.END}\r\n"
        self.assertEqual(readme.update(text, "x\ny"), f"a\r\n{readme.START}\r\nx\r\ny\r\n{readme.END}\r\n")



class FooterVersionTests(TempDirCase):
    def test_changelog_link_reads_version_md(self):
        (self.tmp / "VERSION.md").write_text("1.2.0\n", encoding="utf-8")
        conf = self.tmp / ".githup.yml"
        conf.write_text("site:\n  changelog: https://status.example.com/changelog/\n"
                        "monitors:\n  - name: Web\n    url: https://example.com\n", encoding="utf-8")
        html = site.render(cfg.load(conf), {}, {}, [], now=1_790_000_000)
        self.assertIn('<li><a class="foot-version" href="https://status.example.com/changelog/" '
                      'title="Changelog for v1.2.0">v1.2.0</a></li>', html)

    def test_version_override_and_fallback(self):
        c = make_config(changelog="https://x.test/changelog/", version="v3.1.4")
        self.assertIn(">v3.1.4</a>", site.render(c, {}, {}, [], now=1_790_000_000))
        c = make_config(changelog="https://x.test/changelog/")
        self.assertIn('href="https://x.test/changelog/">Changelog</a>', site.render(c, {}, {}, [], now=1_790_000_000))
        self.assertNotIn('class="foot-version"', site.render(make_config(), {}, {}, [], now=1_790_000_000))


class ReadmeSiteUrlTests(TempDirCase):
    def test_site_url_override(self):
        from unittest import mock
        from githup import cli
        md = self.tmp / "README.md"
        md.write_text(f"{readme.START}\n{readme.END}\n", encoding="utf-8")
        conf = self.tmp / ".githup.yml"
        conf.write_text("monitors:\n  - name: Web\n    url: https://example.com\n", encoding="utf-8")
        args = cli.parser().parse_args(["readme", "--config", str(conf), "--data-dir", str(self.tmp / "data"),
                                        "--readme", str(md), "--no-commit", "--site-url", "https://status.example.com/"])
        with mock.patch.object(cli, "_site_url", side_effect=AssertionError("should not be called")):
            args.func(args)
        self.assertIn("[Live status page](https://status.example.com/)", md.read_text(encoding="utf-8"))

if __name__ == "__main__":
    unittest.main()


class SiteUrlTest(unittest.TestCase):
    def setUp(self):
        from githup import cli
        self.cli = cli
        self.c = cfg.parse({"monitors": [{"name": "A", "url": "https://a.test"}]})

    def test_cname_wins(self):
        c = cfg.parse({"site": {"cname": "status.example.com"}, "monitors": [{"name": "A", "url": "https://a.test"}]})
        self.assertEqual(self.cli._site_url(c, "o/r"), "https://status.example.com/")

    def test_pages_api_url(self):
        from unittest import mock
        with mock.patch.object(self.cli.GitHub, "pages_url", return_value="https://status.example.com"):
            self.assertEqual(self.cli._site_url(self.c, "Owner/Repo"), "https://status.example.com/")

    def test_falls_back_to_github_io(self):
        from unittest import mock
        with mock.patch.object(self.cli.GitHub, "pages_url", side_effect=self.cli.GitHubError(404, "no pages")):
            self.assertEqual(self.cli._site_url(self.c, "Owner/Repo"), "https://owner.github.io/Repo/")
        self.assertEqual(self.cli._site_url(self.c, ""), "")
