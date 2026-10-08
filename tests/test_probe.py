import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from githup import config as cfg
from githup.probe import (DEGRADED, DOWN, INCONCLUSIVE_GRACE, UP, Attempt, Result, classify, code_ok,
                          inconclusive, probe, probe_all)


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


class InconclusiveTests(unittest.TestCase):
    NOW = 1_790_000_000

    def round(self, *codes):
        return [Result(f"m{i}", UP if c == 200 else DOWN, c, 40, self.NOW, 3) for i, c in enumerate(codes)]

    def recent(self, results, age=300):
        return {r.slug: self.NOW - age for r in results}

    def test_most_refused_with_the_same_code_is_held_back(self):
        # The 8 October StuxieDev run: 7 of 9 monitors got 403, the CDN and one site were fine.
        rs = self.round(403, 403, 403, 403, 403, 403, 403, 200, 200)
        self.assertEqual(inconclusive(rs, self.recent(rs), self.NOW), {f"m{i}" for i in range(7)})

    def test_real_outages_are_never_held_back(self):
        rs = self.round(503, 503, 503, 200)
        self.assertEqual(inconclusive(rs, self.recent(rs), self.NOW), set())
        rs = self.round(0, 0, 0)  # timeouts / refused connections
        self.assertEqual(inconclusive(rs, self.recent(rs), self.NOW), set())

    def test_a_minority_or_a_single_refusal_counts(self):
        rs = self.round(403, 200, 200)
        self.assertEqual(inconclusive(rs, self.recent(rs), self.NOW), set())
        rs = self.round(403, 403, 200, 200)  # exactly half: not "most"
        self.assertEqual(inconclusive(rs, self.recent(rs), self.NOW), set())
        rs = self.round(403)  # one monitor can't tell a blocked runner from a blocked site
        self.assertEqual(inconclusive(rs, self.recent(rs), self.NOW), set())

    def test_mixed_codes_only_hold_back_the_main_one(self):
        rs = self.round(403, 403, 403, 429, 200)
        self.assertEqual(inconclusive(rs, self.recent(rs), self.NOW), {"m0", "m1", "m2"})

    def test_results_count_after_the_grace_period(self):
        rs = self.round(403, 403, 403)
        last = self.recent(rs, age=INCONCLUSIVE_GRACE + 1)
        last["m0"] = self.NOW - 300
        self.assertEqual(inconclusive(rs, last, self.NOW), {"m0"})
        self.assertEqual(inconclusive(rs, {}, self.NOW), set())  # never checked: record it


if __name__ == "__main__":
    unittest.main()
