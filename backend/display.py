"""Apply the weekly screen schedule to the Raspberry Pi HDMI output.

The systemd timer calls ``python -m backend.display --apply`` every minute.
On the Wayland desktop shipped with Raspberry Pi OS (labwc), ``wlr-randr``
disables the output; ``vcgencmd display_power`` and the legacy ``tvservice``
remain as fallbacks.  The dashboard process is not stopped: only the video
output is switched off.
"""

from __future__ import annotations

import argparse
import logging
import os
import re
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Callable, Sequence

from .config import ConfigError, load_config
from .night import local_now
from .screen_schedule import (
    describe_schedule,
    is_display_off,
    next_change,
)

DEFAULT_CONFIG_PATH = "/etc/pi-dashboard/config.json"
LOGGER = logging.getLogger("pi-dashboard-display")
Runner = Callable[..., subprocess.CompletedProcess[str]]
WAYLAND_RUNTIME_ROOT = Path("/run/user")
_WLR_OUTPUT_RE = re.compile(r"^(?P<name>[A-Za-z0-9._:-]+)(?:\s+\".*\")?\s*$")


def _run(
    command: list[str],
    runner: Runner = subprocess.run,
    *,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str] | None:
    try:
        return runner(
            command,
            check=False,
            capture_output=True,
            text=True,
            timeout=10,
            env=env,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return None


def _wayland_session() -> tuple[Path, str] | None:
    """Locate the active Wayland socket of the desktop session."""

    try:
        entries = list(WAYLAND_RUNTIME_ROOT.glob("*/wayland-*"))
    except OSError:
        return None
    sockets: list[Path] = []
    for entry in entries:
        try:
            if entry.is_socket():
                sockets.append(entry)
        except OSError:
            continue
    if not sockets:
        return None
    try:
        sockets.sort(key=lambda entry: entry.stat().st_mtime, reverse=True)
    except OSError:
        pass
    socket = sockets[0]
    return socket.parent, socket.name


def _wayland_env(session: tuple[Path, str]) -> dict[str, str]:
    runtime_dir, display = session
    return {
        **os.environ,
        "XDG_RUNTIME_DIR": str(runtime_dir),
        "WAYLAND_DISPLAY": display,
    }


def parse_wlr_outputs(text: str) -> dict[str, bool | None]:
    """Parse ``wlr-randr`` output names and their enabled state."""

    outputs: dict[str, bool | None] = {}
    current: str | None = None
    for raw_line in text.splitlines():
        line = raw_line.rstrip()
        if not line:
            current = None
            continue
        if not line[0].isspace():
            match = _WLR_OUTPUT_RE.match(line)
            current = match.group("name") if match else None
            if current is not None:
                outputs[current] = None
            continue
        if current is None:
            continue
        stripped = line.strip()
        if stripped.casefold().startswith("enabled:"):
            value = stripped.split(":", 1)[1].strip().casefold()
            outputs[current] = value.startswith("yes")
    return outputs


def _wlr_randr_state(
    runner: Runner = subprocess.run,
) -> tuple[tuple[Path, str], str, bool] | None:
    session = _wayland_session()
    if session is None or not shutil.which("wlr-randr"):
        return None
    result = _run(["wlr-randr"], runner=runner, env=_wayland_env(session))
    if result is None or result.returncode != 0:
        return None
    for name, enabled in parse_wlr_outputs(result.stdout or "").items():
        if enabled is not None:
            return session, name, enabled
    return None


def _set_with_wlr_randr(enabled: bool, runner: Runner = subprocess.run) -> bool | None:
    """Return True when changed, False when already correct, None if unusable."""

    state = _wlr_randr_state(runner)
    if state is None:
        return None
    session, output, current = state
    if current == enabled:
        return False
    result = _run(
        ["wlr-randr", "--output", output, "--on" if enabled else "--off"],
        runner=runner,
        env=_wayland_env(session),
    )
    if result is None or result.returncode != 0:
        return None
    LOGGER.info(
        "sortie HDMI %s %s via wlr-randr (%s)",
        output,
        "activée" if enabled else "désactivée",
        session[1],
    )
    return True


def _query_vcgencmd(runner: Runner = subprocess.run) -> bool | None:
    if not shutil.which("vcgencmd"):
        return None
    result = _run(["vcgencmd", "display_power"], runner=runner)
    if result is None or result.returncode != 0:
        return None
    text = f"{result.stdout or ''} {result.stderr or ''}".strip()
    if "display_power=0" in text:
        return False
    if "display_power=1" in text:
        return True
    return None


def _set_with_vcgencmd(enabled: bool, runner: Runner = subprocess.run) -> bool:
    if not shutil.which("vcgencmd"):
        return False
    result = _run(
        ["vcgencmd", "display_power", "1" if enabled else "0"], runner=runner
    )
    return result is not None and result.returncode == 0


def _set_with_tvservice(enabled: bool, runner: Runner = subprocess.run) -> bool:
    if not shutil.which("tvservice"):
        return False
    result = _run(["tvservice", "-p" if enabled else "-o"], runner=runner)
    return result is not None and result.returncode == 0


def set_display_enabled(
    enabled: bool,
    *,
    runner: Runner = subprocess.run,
) -> bool:
    """Power the HDMI output on or off.  Return True when a command was run."""

    wayland = _set_with_wlr_randr(enabled, runner=runner)
    if wayland is not None:
        return wayland

    current = _query_vcgencmd(runner=runner)
    if current is not None and current == enabled:
        return False
    if _set_with_vcgencmd(enabled, runner=runner):
        return True
    if _set_with_tvservice(enabled, runner=runner):
        return True
    LOGGER.warning(
        "aucun outil de contrôle HDMI utilisable (wlr-randr/vcgencmd/tvservice) ; "
        "l'écran n'a pas pu être %s",
        "rallumé" if enabled else "éteint",
    )
    return False


def _print_status(now: datetime, config: dict) -> None:
    schedule = config["screen_schedule"]
    off = is_display_off(now, schedule)
    print(f"Date               : {now.isoformat(timespec='minutes')}")
    print(f"Planification      : {describe_schedule(schedule)}")
    print(f"Écran requis       : {'éteint' if off else 'allumé'}")
    transition = next_change(now, schedule)
    if transition is None:
        print("Prochain changement: aucun")
    else:
        moment, next_off = transition
        print(
            "Prochain changement: "
            f"{moment.isoformat(timespec='minutes')} "
            f"({'extinction' if next_off else 'rallumage'})"
        )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="pi-dashboard-display",
        description="Applique les plages horaires d'extinction de l'écran.",
    )
    parser.add_argument(
        "--config",
        default=DEFAULT_CONFIG_PATH,
        help="chemin du fichier JSON de configuration",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="applique immédiatement l'état calculé (utilisé par systemd)",
    )
    parser.add_argument(
        "--status",
        action="store_true",
        help="affiche l'état calculé sans modifier l'écran",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
        stream=sys.stderr,
    )
    try:
        config = load_config(args.config)
    except ConfigError as exc:
        LOGGER.error("configuration invalide : %s", exc)
        return 2

    now = local_now(config)
    schedule = config["screen_schedule"]
    if args.status or not args.apply:
        _print_status(now, config)
        return 0

    if not schedule["enabled"]:
        return 0
    off = is_display_off(now, schedule)
    set_display_enabled(not off)
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
