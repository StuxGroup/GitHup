import json
import unittest
from datetime import datetime, timezone

from githup import stats
from githup.store import Store, dump_month, month_of
from tests.helpers import TempDirCase, make_config


def ts(y, m, d, h=0, mi=0):
    return int(datetime(y, m, d, h, mi, tzinfo=timezone.utc).timestamp())


class StoreTests(TempDirCase):
    def test_rotation_across_months(self):
        s = Store(self.tmp)
        s.append("web", [[ts(2026, 8, 31, 23, 55), "up", 200, 10], [ts(2026, 9, 1, 0, 0), "down", 503, 20]])
        s.append("web", [[ts(2026, 9, 1, 0, 5), "up", 200, 30]])
        self.assertEqual(s.months("web"), ["2026-08", "2026-09"])
        self.assertEqual(len(s.read_month("web", "2026-08")), 1)
        self.assertEqual([c[3] for c in s.read_month("web", "2026-09")], [20, 30])
        self.assertEqual(len(s.load("web", since=ts(2026, 9, 1))), 2)
        self.assertEqual(len(s.load("web", until=ts(2026, 8, 31, 23, 59))), 1)

    def test_file_format_is_compact_json(self):
        text = dump_month("web", "2026-09", [[1, "up", 200, 5], [2, "down", 0, 9]])
        doc = json.loads(text)
        self.assertEqual(doc["fields"], ["t", "status", "code", "ms"])
        self.assertEqual(doc["checks"][1], [2, "down", 0, 9])
        self.assertEqual(text.count("\n"), 4)  # header, 2 rows, closing
        self.assertNotIn(": ", text)
        self.assertEqual(json.loads(dump_month("a", "2026-01", []))["checks"], [])

    def test_prune(self):
        s = Store(self.tmp)
        for m in (5, 6, 7, 8, 9):
            s.append("web", [[ts(2026, m, 2), "up", 200, 1]])
        removed = s.prune("web", 3, ts(2026, 9, 15))
        self.assertEqual(len(removed), 2)
        self.assertEqual(s.months("web"), ["2026-07", "2026-08", "2026-09"])
        self.assertEqual(s.prune("web", 0, ts(2026, 9, 15)), [])

    def test_summary_roundtrip_and_bad_file(self):
        s = Store(self.tmp)
        self.assertEqual(s.read_summary(), {})
        s.write_summary({"status": "up"})
        self.assertEqual(s.read_summary(), {"status": "up"})
        s.summary_path.write_text("{broken")
        self.assertEqual(s.read_summary(), {})

    def test_month_of(self):
        self.assertEqual(month_of(ts(2026, 12, 31, 23, 59)), "2026-12")


class StatsTests(unittest.TestCase):
    def test_uptime_math(self):
        checks = [[1, "up", 200, 100], [2, "degraded", 200, 300], [3, "down", 0, 9000], [4, "up", 200, 200]]
        self.assertEqual(stats.uptime(checks), 75.0)
        self.assertEqual(stats.avg_ms(checks), 200)  # down checks are excluded
        self.assertIsNone(stats.uptime([]))
        self.assertIsNone(stats.avg_ms([[1, "down", 0, 5]]))

    def test_floor_pct_never_rounds_up_to_100(self):
        self.assertEqual(stats.fmt_pct(99.9999), "99.99%")
        self.assertEqual(stats.fmt_pct(100.0), "100.00%")
        self.assertEqual(stats.fmt_pct(None), "n/a")
        self.assertEqual(stats.fmt_pct(2 / 3 * 100), "66.66%")

    def test_windows(self):
        now = 10 * 86400
        checks = [[now - 2 * 86400, "down", 0, 1], [now - 3600, "up", 200, 1], [now, "up", 200, 1]]
        self.assertEqual(len(stats.window(checks, now, 86400)), 2)
        self.assertEqual(stats.uptime(stats.window(checks, now, stats.WINDOWS["7d"])), 200 / 3)

    def test_totals(self):
        t = stats.add_totals(None, [[5, "up", 200, 10], [3, "down", 0, 99]])
        t = stats.add_totals(t, [[9, "degraded", 200, 30]])
        self.assertEqual(t, {"checks": 3, "available": 2, "ms_sum": 40, "ms_n": 2, "first": 3})
        self.assertAlmostEqual(stats.totals_uptime(t), 200 / 3)
        self.assertEqual(stats.totals_avg(t), 20)

    def test_daily_bars(self):
        now = ts(2026, 9, 29, 12)
        checks = [[ts(2026, 9, 29, 1), "up", 200, 10], [ts(2026, 9, 29, 2), "down", 0, 0],
                  [ts(2026, 9, 28, 1), "up", 200, 10], [ts(2026, 6, 1), "up", 200, 1]]
        days = stats.daily(checks, now, 90)
        self.assertEqual(len(days), 90)
        self.assertEqual(days[-1]["date"], "2026-09-29")
        self.assertEqual((days[-1]["uptime"], days[-1]["down"], days[-1]["level"]), (50.0, 1, "major"))
        self.assertEqual(days[-2]["level"], "ok")
        self.assertEqual(days[0]["level"], "none")

    def test_day_levels(self):
        self.assertEqual(stats.day_level(None, 0, 0), "none")
        self.assertEqual(stats.day_level(100, 0, 288), "ok")
        self.assertEqual(stats.day_level(100, 100, 288), "degraded")
        self.assertEqual(stats.day_level(98, 0, 288), "minor")
        self.assertEqual(stats.day_level(80, 0, 288), "major")

    def test_hourly(self):
        now = 100 * 3600 + 1800
        checks = [[now - 60, "up", 200, 100], [now - 30, "up", 200, 300], [now - 7200, "down", 0, 1]]
        self.assertEqual(stats.hourly_ms(checks, now, 4), [None, None, None, 200])

    def test_overall(self):
        self.assertEqual(stats.overall(["up", "up"]), "up")
        self.assertEqual(stats.overall(["up", "degraded"]), "degraded")
        self.assertEqual(stats.overall(["up", "down"]), "partial")
        self.assertEqual(stats.overall(["down", "down", None]), "down")
        self.assertEqual(stats.overall([None]), "unknown")

    def test_monitor_summary_tracks_last_change(self):
        mon = make_config().monitors[0]
        now = 1_000_000
        checks = [[now - 300, "up", 200, 50], [now, "down", 503, 20]]
        entry = stats.monitor_summary(mon, checks, stats.add_totals(None, checks), {"status": "up"}, now)
        self.assertEqual(entry["status"], "down")
        self.assertEqual(entry["last_change"], {"at": now, "from": "up", "to": "down"})
        self.assertEqual(entry["uptime"]["24h"], 50.0)
        again = stats.monitor_summary(mon, checks, entry["totals"], entry, now + 1)
        self.assertEqual(again["last_change"], entry["last_change"])


if __name__ == "__main__":
    unittest.main()
