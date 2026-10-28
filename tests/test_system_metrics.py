from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from backend.system_metrics import (
    SystemMetrics,
    cpu_percent_from_samples,
    evaluate_health,
    parse_cpu_temperature,
    parse_loadavg,
    parse_meminfo,
    parse_proc_stat,
    parse_uptime,
)
from tests.helpers import make_config

THRESHOLDS = {
    "cpu_warn_percent": 80.0,
    "cpu_critical_percent": 95.0,
    "memory_warn_percent": 80.0,
    "memory_critical_percent": 95.0,
    "temperature_warn_c": 70.0,
    "temperature_critical_c": 80.0,
}

STAT_BEFORE = "cpu  100 0 50 800 50 0 0 0 0 0\ncpu0 1 2 3 4\n"
STAT_AFTER = "cpu  150 0 70 900 50 0 0 0 0 0\ncpu0 1 2 3 4\n"
MEMINFO = """MemTotal:        1024000 kB
MemFree:          200000 kB
MemAvailable:     512000 kB
Buffers:           10000 kB
Cached:           100000 kB
"""


class ParserTests(unittest.TestCase):
    def test_parse_proc_stat_aggregate(self) -> None:
        parsed = parse_proc_stat(STAT_BEFORE)
        self.assertIsNotNone(parsed)
        self.assertEqual(parsed["total"], 1000)
        self.assertEqual(parsed["idle"], 850)

    def test_cpu_percent_between_samples(self) -> None:
        before = parse_proc_stat(STAT_BEFORE)
        after = parse_proc_stat(STAT_AFTER)
        self.assertEqual(cpu_percent_from_samples(before, after), 41.2)
        self.assertEqual(cpu_percent_from_samples(after, after), None)
        self.assertIsNone(cpu_percent_from_samples(None, after))

    def test_parse_meminfo(self) -> None:
        memory = parse_meminfo(MEMINFO)
        self.assertIsNotNone(memory)
        self.assertEqual(memory["total_bytes"], 1024000 * 1024)
        self.assertEqual(memory["available_bytes"], 512000 * 1024)
        self.assertEqual(memory["percent"], 50.0)

    def test_parse_meminfo_without_available_uses_fallback(self) -> None:
        memory = parse_meminfo("MemTotal: 1000 kB\nMemFree: 400 kB\nBuffers: 50 kB\nCached: 50 kB\n")
        self.assertIsNotNone(memory)
        self.assertEqual(memory["available_bytes"], 500 * 1024)
        self.assertEqual(memory["percent"], 50.0)

    def test_parse_uptime_and_loadavg(self) -> None:
        self.assertEqual(parse_uptime("12345.67 1000.00"), 12345.67)
        self.assertEqual(parse_loadavg("0.42 0.31 0.20 1/123 4567"), [0.42, 0.31, 0.2])

    def test_parse_cpu_temperature(self) -> None:
        self.assertEqual(parse_cpu_temperature("48500\n"), 48.5)
        self.assertEqual(parse_cpu_temperature("48.5"), 48.5)
        self.assertIsNone(parse_cpu_temperature("nope"))
        self.assertIsNone(parse_cpu_temperature("999999"))

    def test_malformed_inputs_are_safe(self) -> None:
        self.assertIsNone(parse_proc_stat(""))
        self.assertIsNone(parse_meminfo(""))
        self.assertIsNone(parse_uptime(""))
        self.assertIsNone(parse_loadavg(""))


class HealthTests(unittest.TestCase):
    def test_healthy(self) -> None:
        health = evaluate_health(12.0, 40.0, 48.0, THRESHOLDS)
        self.assertEqual(health["level"], "ok")
        self.assertEqual(health["reasons"], [])

    def test_warning(self) -> None:
        health = evaluate_health(85.0, 40.0, 48.0, THRESHOLDS)
        self.assertEqual(health["level"], "warn")
        self.assertTrue(health["reasons"])

    def test_critical_has_priority(self) -> None:
        health = evaluate_health(99.0, 50.0, 82.0, THRESHOLDS)
        self.assertEqual(health["level"], "critical")
        self.assertGreaterEqual(len(health["reasons"]), 2)

    def test_no_metrics_is_unknown(self) -> None:
        health = evaluate_health(None, None, None, THRESHOLDS)
        self.assertEqual(health["level"], "unknown")


class CollectorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / "proc").mkdir()
        (self.root / "sys" / "class" / "thermal" / "thermal_zone0").mkdir(parents=True)
        (self.root / "proc" / "stat").write_text(STAT_BEFORE, encoding="utf-8")
        (self.root / "proc" / "meminfo").write_text(MEMINFO, encoding="utf-8")
        (self.root / "proc" / "uptime").write_text("12345.67 1000.00\n", encoding="utf-8")
        (self.root / "proc" / "loadavg").write_text("0.42 0.31 0.20 1/123 4567\n", encoding="utf-8")
        (self.root / "sys" / "class" / "thermal" / "thermal_zone0" / "temp").write_text(
            "48500\n", encoding="utf-8"
        )
        config = make_config(Path(self.tmp.name))
        self.metrics_config = config["system"]
        self.now = [0.0]

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_collects_and_caches_metrics(self) -> None:
        metrics = SystemMetrics(
            self.metrics_config,
            root=self.root,
            clock=lambda: self.now[0],
        )
        metrics.prime()
        (self.root / "proc" / "stat").write_text(STAT_AFTER, encoding="utf-8")
        self.now[0] = 10.0
        data = metrics.collect()
        self.assertTrue(data["available"])
        self.assertEqual(data["cpu_percent"], 41.2)
        self.assertEqual(data["cpu_temperature_c"], 48.5)
        self.assertEqual(data["memory"]["percent"], 50.0)
        self.assertEqual(data["uptime_seconds"], 12345)
        self.assertEqual(data["load_average"], [0.42, 0.31, 0.2])
        self.assertEqual(data["health"]["level"], "ok")

        (self.root / "proc" / "meminfo").write_text("", encoding="utf-8")
        cached = metrics.collect()
        self.assertEqual(cached["memory"]["percent"], 50.0)

    def test_missing_procfs_is_reported_not_raised(self) -> None:
        empty = Path(self.tmp.name) / "empty-root"
        empty.mkdir()
        metrics = SystemMetrics(self.metrics_config, root=empty, clock=lambda: 0.0)
        metrics.prime()
        data = metrics.collect()
        self.assertFalse(data["available"])
        self.assertIsNone(data["cpu_percent"])
        self.assertEqual(data["health"]["level"], "unknown")


if __name__ == "__main__":
    unittest.main()
