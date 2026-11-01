from __future__ import annotations

import subprocess
import unittest
from pathlib import Path
from unittest.mock import patch

from backend import display


class FakeRunner:
    def __init__(self, query: str = "display_power=1") -> None:
        self.query = query
        self.commands: list[list[str]] = []

    def __call__(self, command, **_kwargs):
        self.commands.append(list(command))
        if command[-1] == "display_power":
            return subprocess.CompletedProcess(command, 0, self.query, "")
        return subprocess.CompletedProcess(command, 0, "", "")


class WlrRunner:
    """Emulate wlr-randr for a single HDMI output."""

    def __init__(self, enabled: bool = True) -> None:
        self.enabled = enabled
        self.commands: list[list[str]] = []

    def __call__(self, command, **_kwargs):
        self.commands.append(list(command))
        if command == ["wlr-randr"]:
            text = (
                'HDMI-A-1 "Ecran"\n'
                f"  Enabled: {'yes' if self.enabled else 'no'}\n"
                "  Modes:\n"
                "    1920x1080 px, 60.000000 Hz (preferred, current)\n"
            )
            return subprocess.CompletedProcess(command, 0, text, "")
        if command[-1] == "--off":
            self.enabled = False
        elif command[-1] == "--on":
            self.enabled = True
        return subprocess.CompletedProcess(command, 0, "", "")


def _wayland_available():
    return patch.object(
        display,
        "_wayland_session",
        return_value=(Path("/run/user/1000"), "wayland-0"),
    ), patch.object(
        display.shutil,
        "which",
        side_effect=lambda name: "/usr/bin/wlr-randr" if name == "wlr-randr" else None,
    )


class DisplayTests(unittest.TestCase):
    def test_parse_wlr_outputs_ignores_properties(self) -> None:
        text = (
            'HDMI-A-1 "TV"\n'
            "  Enabled: no\n"
            "  Modes:\n"
            "    1920x1080 px, 60.000000 Hz (preferred, current)\n"
            '  Position: 0,0\n'
            'HDMI-A-2 "Second"\n'
            "  Enabled: yes\n"
        )
        self.assertEqual(
            display.parse_wlr_outputs(text),
            {"HDMI-A-1": False, "HDMI-A-2": True},
        )

    def test_wayland_power_off_uses_wlr_randr(self) -> None:
        runner = WlrRunner(enabled=True)
        session_patch, which_patch = _wayland_available()
        with session_patch, which_patch:
            changed = display.set_display_enabled(False, runner=runner)
        self.assertTrue(changed)
        self.assertEqual(
            runner.commands[-1],
            ["wlr-randr", "--output", "HDMI-A-1", "--off"],
        )

    def test_wayland_power_on_uses_wlr_randr(self) -> None:
        runner = WlrRunner(enabled=False)
        session_patch, which_patch = _wayland_available()
        with session_patch, which_patch:
            changed = display.set_display_enabled(True, runner=runner)
        self.assertTrue(changed)
        self.assertEqual(
            runner.commands[-1],
            ["wlr-randr", "--output", "HDMI-A-1", "--on"],
        )

    def test_wayland_already_on_is_idempotent(self) -> None:
        runner = WlrRunner(enabled=True)
        session_patch, which_patch = _wayland_available()
        with session_patch, which_patch:
            changed = display.set_display_enabled(True, runner=runner)
        self.assertFalse(changed)
        self.assertEqual(runner.commands, [["wlr-randr"]])

    def test_power_off_uses_vcgencmd(self) -> None:
        runner = FakeRunner("display_power=1")
        with patch.object(display.shutil, "which", side_effect=lambda name: f"/usr/bin/{name}"):
            changed = display.set_display_enabled(False, runner=runner)
        self.assertTrue(changed)
        self.assertEqual(runner.commands[-1], ["vcgencmd", "display_power", "0"])

    def test_power_on_is_idempotent(self) -> None:
        runner = FakeRunner("display_power=1")
        with patch.object(display.shutil, "which", side_effect=lambda name: f"/usr/bin/{name}"):
            changed = display.set_display_enabled(True, runner=runner)
        self.assertFalse(changed)
        self.assertEqual(runner.commands, [["vcgencmd", "display_power"]])

    def test_tvservice_fallback(self) -> None:
        runner = FakeRunner("")

        def which(name: str) -> str | None:
            return "/usr/bin/tvservice" if name == "tvservice" else None

        with patch.object(display.shutil, "which", side_effect=which):
            changed = display.set_display_enabled(False, runner=runner)
        self.assertTrue(changed)
        self.assertEqual(runner.commands[-1], ["tvservice", "-o"])


if __name__ == "__main__":
    unittest.main()
