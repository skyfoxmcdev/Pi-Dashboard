"""Apply the weekly screen schedule to the Raspberry Pi HDMI output.

The systemd timer calls ``python -m backend.display --apply`` every minute.
``vcgencmd display_power`` is the primary mechanism on Raspberry Pi OS; the
legacy ``tvservice`` command is used as a fallback.  The dashboard process is
not stopped: only the video output is switched off.
"""

from __future__ import annotations

import argparse
import logging
import shutil
import subprocess
import sys
from datetime import datetime
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


def _run(command: list[str], runner: Runner = subprocess.run) -> subprocess.CompletedProcess[str] | None:
    try:
        return runner(
            command,
            check=False,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return None


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

    current = _query_vcgencmd(runner=runner)
    if current is not None and current == enabled:
        return False
    if _set_with_vcgencmd(enabled, runner=runner):
        return True
    if _set_with_tvservice(enabled, runner=runner):
        return True
    LOGGER.warning(
        "aucun outil de contrôle HDMI utilisable (vcgencmd/tvservice) ; "
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
