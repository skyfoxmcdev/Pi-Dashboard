"""Network information for the dashboard.

Wi-Fi details are best-effort: Raspberry Pi OS Desktop normally provides
NetworkManager (nmcli); minimal installations may provide wireless-tools
(iwgetid). Read-only commands are invoked without a shell and with a timeout.
"""

from __future__ import annotations

import copy
import os
import socket
import subprocess
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

Runner = Callable[[list[str]], str | None]


def parse_proc_wireless(text: str) -> dict[str, Any] | None:
    """Parse the first interface of /proc/net/wireless."""

    for line in text.splitlines():
        if ":" not in line or line.lstrip().startswith(("Inter-", "face")):
            continue
        interface, values = line.split(":", 1)
        fields = values.split()
        if len(fields) < 3:
            continue
        try:
            quality = float(fields[1].rstrip("."))
        except (ValueError, IndexError):
            continue
        percent = round(min(100.0, max(0.0, quality / 70.0 * 100.0)))
        return {
            "interface": interface.strip(),
            "signal_percent": percent,
        }
    return None


def parse_ip_addr(text: str) -> str | None:
    """Extract the first global IPv4 address from ``ip -4 -o addr`` output."""

    for line in text.splitlines():
        parts = line.split()
        if "inet" not in parts:
            continue
        try:
            address = parts[parts.index("inet") + 1].split("/", 1)[0]
        except (ValueError, IndexError):
            continue
        if address and not address.startswith("127."):
            return address
    return None


def parse_nmcli_wifi(text: str) -> dict[str, Any] | None:
    """Parse ``nmcli -t -f ACTIVE,SSID,SIGNAL device wifi`` terse output."""

    for line in text.splitlines():
        if not line.startswith("yes:"):
            continue
        before, separator, signal_text = line.rpartition(":")
        if not separator:
            continue
        _, separator, raw_ssid = before.partition(":")
        if not separator:
            continue
        ssid = raw_ssid.replace("\\:", ":").replace("\\\\", "\\").strip()
        try:
            signal = int(signal_text.strip())
        except ValueError:
            signal = None
        return {
            "ssid": ssid or None,
            "signal_percent": max(0, min(100, signal)) if signal is not None else None,
        }
    return None


class NetworkInfo:
    """Cache network readings to avoid spawning commands on every API poll."""

    def __init__(
        self,
        *,
        root: Path | str = Path("/"),
        cache_seconds: float = 15.0,
        clock: Callable[[], float] = time.monotonic,
        runner: Runner | None = None,
        ip_reader: Callable[[], str | None] | None = None,
    ) -> None:
        self._root = Path(root)
        self._cache_seconds = cache_seconds
        self._clock = clock
        self._runner = runner or self._run_command
        self._ip_reader = ip_reader or self._default_ip
        self._lock = threading.Lock()
        self._cache: dict[str, Any] | None = None
        self._cache_time = 0.0

    def _run_command(self, args: list[str]) -> str | None:
        env = os.environ.copy()
        env["PATH"] = env.get("PATH", "") + ":/usr/local/sbin:/usr/sbin:/sbin"
        try:
            completed = subprocess.run(
                args,
                capture_output=True,
                text=True,
                timeout=1.5,
                check=False,
                env=env,
                errors="replace",
            )
        except (OSError, subprocess.SubprocessError):
            return None
        if completed.returncode != 0:
            return None
        return completed.stdout.strip()

    def _wifi_interface(self) -> str | None:
        net_dir = self._root / "sys" / "class" / "net"
        try:
            entries = list(net_dir.iterdir())
        except OSError:
            entries = []
        for entry in entries:
            if (entry / "wireless").exists():
                return entry.name

        text = self._read(self._root / "proc" / "net" / "wireless")
        parsed = parse_proc_wireless(text) if text else None
        return parsed["interface"] if parsed else None

    @staticmethod
    def _read(path: Path) -> str | None:
        try:
            return path.read_text(encoding="utf-8", errors="replace").strip()
        except OSError:
            return None

    def _default_ip(self) -> str | None:
        # Connecting a UDP socket selects a route without sending a packet.
        sock = None
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.settimeout(0.5)
            sock.connect(("192.0.2.1", 9))
            address = sock.getsockname()[0]
            if address and not address.startswith("127."):
                return address
        except OSError:
            pass
        finally:
            if sock is not None:
                try:
                    sock.close()
                except OSError:
                    pass

        output = self._runner(["ip", "-4", "-o", "addr", "show", "scope", "global"])
        return parse_ip_addr(output) if output else None

    def _wifi_details(self, interface: str | None) -> dict[str, Any]:
        if interface is None:
            return {
                "available": False,
                "connected": False,
                "ssid": None,
                "signal_percent": None,
                "interface": None,
            }

        ssid = self._runner(["iwgetid", "-r"])
        ssid = ssid.strip() if ssid else ""
        signal_percent: int | None = None

        proc_text = self._read(self._root / "proc" / "net" / "wireless")
        parsed = parse_proc_wireless(proc_text) if proc_text else None
        if parsed and parsed["interface"] == interface:
            signal_percent = parsed["signal_percent"]

        if not ssid:
            output = self._runner(
                ["nmcli", "-t", "-f", "ACTIVE,SSID,SIGNAL", "device", "wifi"]
            )
            nm = parse_nmcli_wifi(output) if output else None
            if nm:
                ssid = nm["ssid"] or ""
                if signal_percent is None:
                    signal_percent = nm["signal_percent"]

        operstate = self._read(self._root / "sys" / "class" / "net" / interface / "operstate")
        carrier = self._read(self._root / "sys" / "class" / "net" / interface / "carrier")
        connected = bool(ssid) or operstate == "up" or carrier == "1"
        return {
            "available": True,
            "connected": connected,
            "ssid": ssid or None,
            "signal_percent": signal_percent,
            "interface": interface,
        }

    def collect(self) -> dict[str, Any]:
        with self._lock:
            now = self._clock()
            if self._cache is not None and (now - self._cache_time) < self._cache_seconds:
                return copy.deepcopy(self._cache)

            interface = self._wifi_interface()
            wifi = self._wifi_details(interface)
            result = {
                "wifi": wifi,
                "ip_address": self._ip_reader(),
                "checked_at": datetime.now().astimezone().isoformat(timespec="seconds"),
            }
            self._cache = result
            self._cache_time = now
            return copy.deepcopy(result)
