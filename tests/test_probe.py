import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from githup import config as cfg
from githup.probe import DEGRADED, DOWN, UP, Attempt, classify, code_ok, probe, probe_all


def monitor(**kw):
    base = {"name": "t", "url": "https://t.test", "retry_delay": 0}
    base.update(kw)
    return cfg.parse({"monitors": [base]}).monitors[0]


class ClassifyTests(unittest.TestCase):
    def test_default_range(self):
        exp = cfg.DEFAULT_EXPECTED
        self.assertEqual(classify(200, 10, exp, None), UP)
        self.assertEqual(classify(301, 10, exp, None), UP)
        self.assertEqual(classify(404, 10, exp, None), DOWN)
        self.assertEqual(classify(503, 10, exp, None), DOWN)
        self.assertEqual(classify(0, 10, exp, None), DOWN)

    def test_only_200(self):
        exp = ((200, 200),)
        self.assertTrue(code_ok(200, exp))
        self.assertEqual(classify(204, 1, exp, None), DOWN)

    def test_degraded(self):
        exp = cfg.DEFAULT_EXPECTED
        self.assertEqual(classify(200, 1500, exp, 1000), DEGRADED)
        self.assertEqual(classify(200, 1000, exp, 1000), UP)
        self.assertEqual(classify(500, 5000, exp, 1000), DOWN)


class RetryTests(unittest.TestCase):
    def fake(self, attempts):
        calls = []

        def fetch(m, url, headers, body):
            calls.append((url, headers))
            return attempts[min(len(calls) - 1, len(attempts) - 1)]
        return fetch, calls

    def test_recovers_on_retry(self):
        fetch, calls = self.fake([Attempt(0, 5, "reset"), Attempt(200, 40)])
        r = probe(monitor(retries=2), fetcher=fetch, sleep=lambda s: None, clock=lambda: 1000)
        self.assertEqual((r.status, r.code, r.ms, r.attempts, r.checked_at), (UP, 200, 40, 2, 1000))
        self.assertEqual(len(calls), 2)

    def test_down_after_all_retries(self):
        fetch, calls = self.fake([Attempt(503, 20, "HTTP 503")])
        r = probe(monitor(retries=2), fetcher=fetch, sleep=lambda s: None)
        self.assertEqual((r.status, r.code, r.attempts), (DOWN, 503, 3))
        self.assertEqual(r.error, "HTTP 503")

    def test_degraded_is_not_retried(self):
        fetch, calls = self.fake([Attempt(200, 5000)])
        r = probe(monitor(max_response_time=100), fetcher=fetch, sleep=lambda s: None)
        self.assertEqual((r.status, r.attempts), (DEGRADED, 1))

    def test_headers_expanded_and_missing_skipped(self):
        fetch, calls = self.fake([Attempt(200, 1)])
        ok = monitor(name="ok", headers={"Authorization": "Bearer ${{ secrets.TOK }}"})
        bad = monitor(name="bad", headers={"X": "${NOPE}"})
        results, skipped = probe_all([ok, bad], env={}, secrets={"TOK": "s3cret"}, fetcher=fetch,
                                     sleep=lambda s: None)
        self.assertEqual([r.slug for r in results], ["ok"])
        self.assertIn("NOPE", skipped["bad"])
        self.assertEqual(calls[0][1]["Authorization"], "Bearer s3cret")


class _Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        code = int(self.path.strip("/") or 200)
        if code in (301, 302):
            self.send_response(code)
            self.send_header("Location", "/200")
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        self.send_response(code)
        self.send_header("Content-Length", "2")
        self.end_headers()
        self.wfile.write(b"ok")

    def log_message(self, *a):
        pass


class RealHttpTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
        cls.base = f"http://127.0.0.1:{cls.server.server_address[1]}"
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def test_real_codes(self):
        self.assertEqual(probe(monitor(url=f"{self.base}/200")).status, UP)
        r = probe(monitor(url=f"{self.base}/503", retries=0))
        self.assertEqual((r.status, r.code), (DOWN, 503))
        r = probe(monitor(url=f"{self.base}/200", expected=[201], retries=0))
        self.assertEqual(r.status, DOWN)

    def test_redirects(self):
        self.assertEqual(probe(monitor(url=f"{self.base}/301")).code, 200)
        r = probe(monitor(url=f"{self.base}/301", follow_redirects=False, retries=0))
        self.assertEqual((r.code, r.status), (301, UP))

    def test_connection_refused(self):
        r = probe(monitor(url="http://127.0.0.1:1/", retries=0, timeout=2))
        self.assertEqual((r.status, r.code), (DOWN, 0))
        self.assertTrue(r.error)


if __name__ == "__main__":
    unittest.main()
