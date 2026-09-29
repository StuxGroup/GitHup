import unittest

from githup.yamlish import YAMLError, loads


class YamlSubsetTests(unittest.TestCase):
    def test_nested_mapping_and_sequences(self):
        doc = loads("""
# comment
site:
  name: My Status   # trailing comment
  accent: "#a349a4"
monitors:
  - name: Web
    url: https://example.com
    expected: [200, "300-399", 404]
  - name: API
    headers:
      Authorization: "Bearer ${{ secrets.TOKEN }}"
""")
        self.assertEqual(doc["site"], {"name": "My Status", "accent": "#a349a4"})
        self.assertEqual(doc["monitors"][0]["expected"], [200, "300-399", 404])
        self.assertEqual(doc["monitors"][0]["url"], "https://example.com")
        self.assertEqual(doc["monitors"][1]["headers"]["Authorization"], "Bearer ${{ secrets.TOKEN }}")

    def test_scalars(self):
        doc = loads("a: 1\nb: 1.5\nc: true\nd: false\ne: null\nf: ~\ng: yes\nh: 'it''s'\ni: \"x\\ny\"\nj:\nk: []\nl: {}\n")
        self.assertEqual(doc, {"a": 1, "b": 1.5, "c": True, "d": False, "e": None, "f": None,
                               "g": "yes", "h": "it's", "i": "x\ny", "j": None, "k": [], "l": {}})

    def test_apostrophe_and_hash_in_plain_scalar(self):
        doc = loads("d: Keep track of RoboStux's services\nu: https://x.test/#frag\n")
        self.assertEqual(doc["d"], "Keep track of RoboStux's services")
        self.assertEqual(doc["u"], "https://x.test/#frag")

    def test_sequence_at_same_indent_as_key(self):
        self.assertEqual(loads("items:\n- a\n- b\nnext: 1\n"), {"items": ["a", "b"], "next": 1})

    def test_list_of_scalars_and_nested_lists(self):
        self.assertEqual(loads("- a\n- - b\n  - c\n-\n  x: 1\n"), ["a", ["b", "c"], {"x": 1}])

    def test_empty_document(self):
        self.assertIsNone(loads("# nothing\n\n"))

    def test_errors(self):
        bad = {
            "a: 1\na: 2\n": "duplicate",
            "a:\n\tb: 1\n": "tabs",
            "a: &x 1\n": "unsupported",
            "a: |\n  text\n": "unsupported",
            "a: [1, [2]]\n": "nested",
            "a: {b: 1}\n": "flow mappings",
            "a: 'open\n": "unterminated",
            "a: 1\n  b: 2\n": "indentation",
            "just text\n": "expected",
            "a: \"x\" y\n": "unexpected text",
            "a: 1\n---\nb: 2\n": "multiple documents",
        }
        for text, needle in bad.items():
            with self.subTest(text=text):
                with self.assertRaises(YAMLError) as ctx:
                    loads(text)
                self.assertIn(needle, str(ctx.exception))

    def test_error_has_line_number(self):
        with self.assertRaises(YAMLError) as ctx:
            loads("a: 1\nb: 2\nb: 3\n")
        self.assertEqual(ctx.exception.line, 3)


if __name__ == "__main__":
    unittest.main()
