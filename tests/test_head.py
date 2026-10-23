"""Favicon set, site.webmanifest and the Discord component embed on every generated page."""

import json
import re
import unittest
from html.parser import HTMLParser

from githup import config as cfg, discord, site
from githup.store import Store
from tests.helpers import TempDirCase
from tests.test_pages import LEGAL, MON, SLUGS, conf

NOW = 1_790_000_000
EMBED_RE = re.compile(r'<script id="discord:component-embed" type="application/json">(.*?)</script>', re.S)
ALLOWED_TYPES = {1, 2, 9, 10, 11, 12, 14, 17}
BUTTON_KEYS = {"id", "type", "url", "style", "label", "emoji", "disabled"}


def walk(node):
    yield node
    for child in node.get("components", []):
        yield from walk(child)
    if "accessory" in node:
        yield from walk(node["accessory"])


def check_embed(case, html):
    m = EMBED_RE.search(html)
    case.assertIsNotNone(m, "embed missing")
    raw = m.group(1)
    case.assertLessEqual(len(raw.encode("utf-8")), discord.MAX_BYTES)
    case.assertNotIn("</", raw)
    case.assertNotIn("$1", raw)
    root = json.loads(raw)["component"]
    case.assertEqual(root["type"], 17)
    nodes = list(walk(root))
    case.assertLessEqual(len(nodes), 40)
    case.assertEqual(sum(1 for n in nodes if n["type"] == 17), 1)
    for n in nodes:
        case.assertIn(n["type"], ALLOWED_TYPES)
        if n["type"] == 2:
            case.assertEqual(n["style"], 5)
            case.assertTrue(set(n) <= BUTTON_KEYS)
            case.assertRegex(n["url"], r"^https?://")
    return root


class _Head(HTMLParser):
    def __init__(self):
        super().__init__()
        self.links, self.in_head = [], False

    def handle_starttag(self, tag, attrs):
        if tag == "head":
            self.in_head = True
        if tag == "link" and self.in_head:
            self.links.append(dict(attrs))

    def handle_endtag(self, tag):
        if tag == "head":
            self.in_head = False


class HeadTests(TempDirCase):
    def build(self, c):
        return site.build(c, Store(self.tmp / "data"), self.tmp / "out", now=NOW)

    def pages(self, out):
        rels = ["index.html", "404.html", "sitemap/index.html", "legal/index.html"]
        return rels + [f"legal/{s}/index.html" for s in SLUGS]

    def test_favicon_files_and_manifest(self):
        out = self.build(conf(LEGAL, cname="status.acme.test", accent="#a349a4", short_name="Acme"))
        for name in ("favicon.ico", "apple-touch-icon.png", "icon-192.png", "icon-512.png", "icon-maskable-512.png"):
            self.assertTrue((out / name).is_file(), name)
        man = json.loads((out / "site.webmanifest").read_text(encoding="utf-8"))
        self.assertEqual((man["name"], man["short_name"], man["start_url"], man["display"]),
                         ("Acme Status", "Acme", "/", "browser"))
        self.assertEqual((man["theme_color"], man["background_color"]), ("#a349a4", "#ffffff"))
        sizes = {(i["sizes"], i.get("purpose")) for i in man["icons"]}
        self.assertEqual(sizes, {("192x192", None), ("512x512", None), ("512x512", "maskable")})

    def test_manifest_colours_configurable(self):
        out = self.build(conf(theme_color="#123", background_color="#000000"))
        man = json.loads((out / "site.webmanifest").read_text(encoding="utf-8"))
        self.assertEqual((man["theme_color"], man["background_color"]), ("#112233", "#000000"))
        self.assertIn('content="#112233"', (out / "index.html").read_text(encoding="utf-8"))

    def test_own_icons_folder_wins(self):
        icons = self.tmp / "brand"
        icons.mkdir()
        (icons / "favicon.ico").write_bytes(b"OWN")
        c = cfg.parse({"site": {"name": "X", "icons": "brand"}, "monitors": MON}, path=str(self.tmp / ".githup.yml"))
        out = self.build(c)
        self.assertEqual((out / "favicon.ico").read_bytes(), b"OWN")
        self.assertGreater((out / "icon-512.png").stat().st_size, 1000)  # missing files fall back to the default
        with self.assertRaises(cfg.ConfigError):
            conf(icons="../outside")

    def test_every_page_has_the_head_tags(self):
        out = self.build(conf(LEGAL, cname="status.acme.test"))
        for rel in self.pages(out):
            html = (out / rel).read_text(encoding="utf-8")
            root = "/" if rel == "404.html" else ("./" if rel == "index.html" else "../" * rel.count("/"))
            p = _Head()
            p.feed(html)
            hrefs = {(l.get("rel"), l.get("sizes")): l["href"] for l in p.links}
            self.assertEqual(hrefs[("icon", "48x48")], root + "favicon.ico", rel)
            self.assertEqual(hrefs[("icon", "512x512")], root + "icon-512.png", rel)
            self.assertEqual(hrefs[("apple-touch-icon", None)], root + "apple-touch-icon.png", rel)
            self.assertEqual(hrefs[("manifest", None)], root + "site.webmanifest", rel)
            self.assertIn("manifest-src 'self'", html)

    def test_embed_on_every_page_but_404(self):
        out = self.build(conf(LEGAL, cname="status.acme.test", description="Acme *services* [x](y)"))
        for rel in self.pages(out):
            html = (out / rel).read_text(encoding="utf-8")
            if rel == "404.html":
                self.assertNotIn("discord:component-embed", html)
                continue
            root = check_embed(self, html)
            self.assertEqual(root["accent_color"], 0x3BA7FF)
        main = json.loads(EMBED_RE.search((out / "index.html").read_text(encoding="utf-8")).group(1))
        flat = main["component"]["components"][0]["components"][0]["content"]
        self.assertIn(r"Acme \*services\* \[x\]", flat)
        self.assertIn("https://status.acme.test/legal/", json.dumps(main))

    def test_embed_without_base_url_has_no_buttons(self):
        out = self.build(conf(LEGAL))
        root = check_embed(self, (out / "index.html").read_text(encoding="utf-8"))
        self.assertFalse([n for n in walk(root) if n["type"] in (1, 2)])

    def test_hostile_names_cannot_break_out(self):
        out = self.build(conf(LEGAL, name="</script><b>#*_~`|>Acme", cname="status.acme.test"))
        for rel in ("index.html", "legal/privacy/index.html"):
            check_embed(self, (out / rel).read_text(encoding="utf-8"))


class DiscordTests(unittest.TestCase):
    def test_md_escapes_once(self):
        self.assertEqual(discord.md(r"a*b_c~d`e|f[g]h\i"), r"a\*b\_c\~d\`e\|f\[g\]h\\i")
        self.assertEqual(discord.md("# h\n> q\n- l"), "\\# h\n\\> q\n\\- l")
        self.assertEqual(discord.md("a*b"), r"a\*b")  # never a literal "$1"

    def test_over_limit_becomes_comment(self):
        out = discord.embed([discord.text("x" * 3200)], "#3ba7ff")
        self.assertTrue(out.startswith("<!--"))
        self.assertNotIn("<script", out)

    def test_script_close_is_neutralised(self):
        out = discord.embed([discord.text("</script><!--")], "#3ba7ff")
        self.assertEqual(out.count("</script>"), 1)
        self.assertEqual(json.loads(EMBED_RE.search(out).group(1))["component"]["components"][0]["content"],
                         "</script><!--")

    def test_buttons_only_http(self):
        row = discord.buttons([("a", "javascript:alert(1)"), ("b", "https://example.com/")])
        self.assertEqual(row["components"], [{"type": 2, "style": 5, "label": "b", "url": "https://example.com/"}])
        self.assertIsNone(discord.buttons([("a", "ftp://x")]))


if __name__ == "__main__":
    unittest.main()
