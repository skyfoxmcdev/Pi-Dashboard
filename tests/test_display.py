from __future__ import annotations

import subprocess
import unittest
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


class DisplayTests(unittest.TestCase):
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
