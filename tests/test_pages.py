import unittest
import xml.etree.ElementTree as ET

from githup import config as cfg, site
from githup.store import Store
from tests.helpers import TempDirCase
from tests.test_site_readme import _Checker

NOW = 1_790_000_000
MON = [{"name": "Web", "url": "https://example.com"}]
LEGAL = {"operator": "Acme <Ops>", "company": "Acme Ltd, no. 123 & registered office 1 High St",
         "contact": "legal@acme.test", "effective": "1 October 2026"}
SLUGS = ("privacy", "terms", "cookies", "imprint", "disclaimer", "opt-out")


def conf(legal_block=None, **site_keys):
    data = {"site": {"name": "Acme Status", **site_keys}, "monitors": MON}
    if legal_block is not None:
        data["legal"] = legal_block
    return cfg.parse(data)


class ConfigTests(unittest.TestCase):
    def test_legal_block(self):
        c = conf(LEGAL)
        self.assertEqual((c.legal.operator, c.legal.contact, c.legal.host), ("Acme <Ops>", "legal@acme.test", "GitHub Pages"))
        self.assertIsNone(conf().legal)

    def test_legal_validation(self):
        for bad in ({"nope": 1}, {"contact": "not an email"}, {"operator": ["x"]}, "text"):
            with self.assertRaises(cfg.ConfigError, msg=bad):
                conf(bad)

    def test_url_validation(self):
        self.assertEqual(conf(url="https://example.com/status").site.url, "https://example.com/status")
        with self.assertRaises(cfg.ConfigError):
            conf(url="example.com")


class BuildTests(TempDirCase):
    def build(self, c, dev=False, name="out"):
        return site.build(c, Store(self.tmp / "data"), self.tmp / name, now=NOW, dev_mode=dev)

    def test_legal_pages_generated(self):
        out = self.build(conf(LEGAL, cname="status.acme.test"), dev=True)
        for rel in ["legal/index.html"] + [f"legal/{s}/index.html" for s in SLUGS]:
            html = (out / rel).read_text(encoding="utf-8")
            chk = _Checker()
            chk.feed(html)
            self.assertEqual((chk.errors, chk.stack, chk.external), ([], [], []), rel)
            self.assertIn("Acme Status", html)
            self.assertIn("1 October 2026", html)
            self.assertIn("prefers-color-scheme: dark", html)
            self.assertIn("site-banner--dev", html)  # the banner component
            self.assertIn("A Stux.Group Service", html)
            self.assertIn("Powered by GitHup", html)
            self.assertIn("Boring Legal Stuff", html)
        hub = (out / "legal/index.html").read_text(encoding="utf-8")
        for s in SLUGS:
            self.assertIn(f'href="{s}/"', hub)
        imprint = (out / "legal/imprint/index.html").read_text(encoding="utf-8")
        self.assertIn("Acme &lt;Ops&gt;", imprint)  # escaped operator
        self.assertNotIn("<Ops>", imprint)
        self.assertIn("Acme Ltd, no. 123 &amp; registered", imprint)
        self.assertIn('href="mailto:legal@acme.test"', imprint)
        self.assertIn("GitHub Pages", imprint)
        self.assertIn('href="../../">Acme Status</a>', imprint)  # relative links work in subfolders
        self.assertIn("legal@acme.test", (out / "legal/privacy/index.html").read_text(encoding="utf-8"))

    def test_no_legal_block_no_legal_pages(self):
        out = self.build(conf(legal="https://acme.test/legal"))
        self.assertFalse((out / "legal").exists())
        html = (out / "index.html").read_text(encoding="utf-8")
        self.assertIn('href="https://acme.test/legal">Boring Legal Stuff</a>', html)

    def test_generated_legal_wins_over_site_legal(self):
        html = (self.build(conf(LEGAL, legal="https://acme.test/legal")) / "index.html").read_text(encoding="utf-8")
        self.assertIn('href="./legal/">Boring Legal Stuff</a>', html)
        self.assertNotIn("acme.test/legal", html)

    def test_404(self):
        out = self.build(conf(LEGAL, cname="status.acme.test"), dev=True)
        html = (out / "404.html").read_text(encoding="utf-8")
        chk = _Checker()
        chk.feed(html)
        self.assertEqual((chk.errors, chk.stack), ([], []))
        self.assertIn("Page not found", html)
        self.assertIn('href="/">&larr; Go to the status page</a>', html)  # absolute: served from any depth
        self.assertIn("site-banner--dev", html)
        self.assertIn("A Stux.Group Service", html)
        self.assertIn("<header", html)
        self.assertIn("<footer", html)

    def test_404_without_known_base_uses_relative_home(self):
        html = (self.build(conf()) / "404.html").read_text(encoding="utf-8")
        self.assertIn('href="./">&larr; Go to the status page</a>', html)

    def test_sitemap_xml(self):
        out = self.build(conf(LEGAL, cname="status.acme.test"))
        root = ET.parse(out / "sitemap.xml").getroot()
        ns = {"s": "http://www.sitemaps.org/schemas/sitemap/0.9"}
        locs = [e.text for e in root.findall("s:url/s:loc", ns)]
        base = "https://status.acme.test/"
        self.assertEqual(locs, [base, base + "legal/"] + [f"{base}legal/{s}/" for s in SLUGS])
        robots = (out / "robots.txt").read_text(encoding="utf-8")
        self.assertIn(f"Sitemap: {base}sitemap.xml", robots)
        page = (out / "sitemap/index.html").read_text(encoding="utf-8")
        chk = _Checker()
        chk.feed(page)
        self.assertEqual((chk.errors, chk.stack), ([], []))
        self.assertIn("Privacy Policy", page)
        self.assertIn('href="../legal/privacy/"', page)
        self.assertIn('href="../sitemap/">Sitemap</a>', page)
        index = (out / "index.html").read_text(encoding="utf-8")
        self.assertIn('href="./sitemap/">Sitemap</a>', index)

    def test_sitemap_uses_site_url_and_only_status_page_without_legal(self):
        out = self.build(conf(url="https://acme.github.io/status"))
        root = ET.parse(out / "sitemap.xml").getroot()
        locs = [e.text for e in root.iter("{http://www.sitemaps.org/schemas/sitemap/0.9}loc")]
        self.assertEqual(locs, ["https://acme.github.io/status/"])
        self.assertIn("/status/", (out / "404.html").read_text(encoding="utf-8"))

    def test_no_base_url_skips_sitemap(self):
        logs = []
        out = site.build(conf(LEGAL), Store(self.tmp / "data"), self.tmp / "o", now=NOW, log=logs.append)
        for rel in ("sitemap.xml", "robots.txt", "sitemap"):
            self.assertFalse((out / rel).exists(), rel)
        self.assertNotIn("Sitemap</a>", (out / "index.html").read_text(encoding="utf-8"))
        self.assertTrue(any("skipping sitemap" in m for m in logs))

    def test_existing_robots_txt_is_kept(self):
        target = self.tmp / "out"
        target.mkdir()
        (target / "robots.txt").write_text("User-agent: *\nDisallow: /private\n", encoding="utf-8")
        out = self.build(conf(cname="status.acme.test"))
        self.assertEqual((out / "robots.txt").read_text(encoding="utf-8"), "User-agent: *\nDisallow: /private\n")
        self.assertTrue((out / "sitemap.xml").exists())


if __name__ == "__main__":
    unittest.main()
