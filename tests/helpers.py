import tempfile
import unittest
from pathlib import Path

from githup import config as cfg

EXAMPLE = Path(__file__).resolve().parent.parent / "examples" / ".githup.yml"


def make_config(monitors=None, **site):
    data = {"site": {"name": "Test Status", "legal": "https://example.com/legal", **site},
            "monitors": monitors or [{"name": "Web", "url": "https://example.com"},
                                     {"name": "API", "url": "https://api.example.com", "expected": [200]}]}
    return cfg.parse(data)


class TempDirCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()
