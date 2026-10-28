from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from backend.network import (
    NetworkInfo,
    parse_ip_addr,
    parse_nmcli_wifi,
    parse_proc_wireless,
)

WIRELESS = """Inter-| sta-|   Quality        |   Discarded packets               | Missed | WE
 face | tus | link level noise |  nwid  crypt   frag  retry   misc | beacon | 22
 wlan0: 0000   63.  -47.  -256        0      0      0      0      0        0
"""

IP_OUTPUT = """2: wlan0    inet 192.168.1.42/24 brd 192.168.1.255 scope global dynamic wlan0
       valid_lft 84000sec preferred_lft 84000sec
"""

NMCLI = """no:Other WiFi:30
yes:Maison\\:5G:78
"""


class NetworkParserTests(unittest.TestCase):
    def test_proc_wireless(self) -> None:
        parsed = parse_proc_wireless(WIRELESS)
        self.assertEqual(parsed["interface"], "wlan0")
        self.assertEqual(parsed["signal_percent"], 90)

    def test_ip_addr(self) -> None:
        self.assertEqual(parse_ip_addr(IP_OUTPUT), "192.168.1.42")
        self.assertIsNone(parse_ip_addr("1: lo inet 127.0.0.1/8 scope host lo"))

    def test_nmcli_escaped_ssid(self) -> None:
        parsed = parse_nmcli_wifi(NMCLI)
        self.assertEqual(parsed["ssid"], "Maison:5G")
        self.assertEqual(parsed["signal_percent"], 78)

    def test_malformed(self) -> None:
        self.assertIsNone(parse_proc_wireless(""))
        self.assertIsNone(parse_nmcli_wifi(""))


class NetworkCollectorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        net = self.root / "sys" / "class" / "net" / "wlan0"
        (net / "wireless").mkdir(parents=True)
        (net / "operstate").write_text("up\n", encoding="utf-8")
        (net / "carrier").write_text("1\n", encoding="utf-8")
        proc_net = self.root / "proc" / "net"
        proc_net.mkdir(parents=True)
        (proc_net / "wireless").write_text(WIRELESS, encoding="utf-8")

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_collects_wifi_and_ip(self) -> None:
        def runner(args):
            if args[:2] == ["iwgetid", "-r"]:
                return "Maison"
            return None

        info = NetworkInfo(
            root=self.root,
            cache_seconds=0,
            runner=runner,
            ip_reader=lambda: "192.168.1.42",
        )
        data = info.collect()
        self.assertTrue(data["wifi"]["available"])
        self.assertTrue(data["wifi"]["connected"])
        self.assertEqual(data["wifi"]["ssid"], "Maison")
        self.assertEqual(data["wifi"]["signal_percent"], 90)
        self.assertEqual(data["wifi"]["interface"], "wlan0")
        self.assertEqual(data["ip_address"], "192.168.1.42")

    def test_falls_back_to_nmcli(self) -> None:
        (self.root / "proc" / "net" / "wireless").unlink()

        def runner(args):
            if args[0] == "iwgetid":
                return None
            if args[0] == "nmcli":
                return NMCLI
            return None

        info = NetworkInfo(
            root=self.root,
            cache_seconds=0,
            runner=runner,
            ip_reader=lambda: None,
        )
        data = info.collect()
        self.assertEqual(data["wifi"]["ssid"], "Maison:5G")
        self.assertEqual(data["wifi"]["signal_percent"], 78)

    def test_ethernet_only_has_no_wifi(self) -> None:
        empty_root = Path(self.tmp.name) / "empty"
        empty_root.mkdir()
        info = NetworkInfo(
            root=empty_root,
            cache_seconds=0,
            runner=lambda args: None,
            ip_reader=lambda: "10.0.0.2",
        )
        data = info.collect()
        self.assertFalse(data["wifi"]["available"])
        self.assertFalse(data["wifi"]["connected"])
        self.assertIsNone(data["wifi"]["ssid"])
        self.assertEqual(data["ip_address"], "10.0.0.2")

    def test_cache_avoids_repeated_raw_reads(self) -> None:
        calls = []

        def runner(args):
            calls.append(args)
            return "Maison"

        now = [100.0]
        info = NetworkInfo(
            root=self.root,
            cache_seconds=15,
            clock=lambda: now[0],
            runner=runner,
            ip_reader=lambda: "192.168.1.42",
        )
        info.collect()
        first_calls = len(calls)
        now[0] += 5
        info.collect()
        self.assertEqual(len(calls), first_calls)


if __name__ == "__main__":
    unittest.main()
