"""CLI entrypoint for the Pi Dashboard backend."""

from __future__ import annotations

import argparse
import logging
import os
import signal
import sys
import threading
from pathlib import Path
from typing import Sequence

from . import APP_NAME, __version__
from .config import ConfigError, load_config
from .dashboard import DashboardApp
from .http_server import create_server

DEFAULT_CONFIG_PATH = "/etc/pi-dashboard/config.json"
LOGGER = logging.getLogger("pi-dashboard")


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="pi-dashboard",
        description="Tableau de bord local pour Raspberry Pi (kiosque 1920x1080).",
    )
    parser.add_argument(
        "--config",
        default=os.environ.get("PI_DASHBOARD_CONFIG", DEFAULT_CONFIG_PATH),
        help="chemin du fichier JSON de configuration",
    )
    parser.add_argument(
        "--check-config",
        action="store_true",
        help="valide la configuration puis quitte",
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=("DEBUG", "INFO", "WARNING"),
        help="niveau de journalisation (défaut: INFO)",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"{APP_NAME} {__version__}",
    )
    return parser.parse_args(argv)


def _print_config_summary(config: dict, path: str) -> None:
    location = config["location"]
    weather = config["weather"]
    night = config["night_mode"]
    coordinates = (
        f"{location['latitude']}, {location['longitude']}"
        if location["latitude"] is not None
        else "non renseignées (météo indisponible)"
    )
    print(f"Configuration valide : {path}")
    print(f"Lieu : {location['name']}")
    print(f"Coordonnées : {coordinates}")
    print(f"Fuseau horaire : {location['timezone']}")
    print(f"Cache météo : {weather['cache_file']}")
    print(
        "Mode nuit : "
        + (
            f"activé de {night['start']} à {night['end']}"
            if night["enabled"]
            else "désactivé"
        )
    )
    print(f"Écoute : http://{config['server']['host']}:{config['server']['port']}")
    warnings = config.get("_meta", {}).get("warnings", [])
    if warnings:
        print("\nAvertissements :")
        for warning in warnings:
            print(f" - {warning}")
    else:
        print("Avertissements : aucun")


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
        stream=sys.stderr,
    )

    try:
        config = load_config(args.config)
    except ConfigError as exc:
        LOGGER.error("Configuration invalide : %s", exc)
        return 2

    if args.check_config:
        _print_config_summary(config, args.config)
        return 0

    if hasattr(os, "geteuid") and os.geteuid() == 0:
        LOGGER.error(
            "Refus de démarrer en root. Le service doit tourner avec "
            "l'utilisateur système non privilégié « pi-dashboard »."
        )
        return 3

    for warning in config.get("_meta", {}).get("warnings", []):
        LOGGER.warning("%s", warning)

    frontend_dir = Path(__file__).resolve().parent.parent / "frontend"
    if not (frontend_dir / "index.html").is_file():
        LOGGER.error("Interface introuvable : %s/index.html", frontend_dir)
        return 4

    location = config["location"]
    LOGGER.info(
        "%s %s — lieu : %s (météo %s)",
        APP_NAME,
        __version__,
        location["name"],
        "configurée" if location["latitude"] is not None else "non configurée",
    )

    app = DashboardApp(config, frontend_dir, logger=LOGGER)
    try:
        server = create_server(
            app,
            frontend_dir,
            config["server"]["host"],
            config["server"]["port"],
        )
    except OSError as exc:
        LOGGER.error(
            "Impossible d'écouter sur %s:%s — %s",
            config["server"]["host"],
            config["server"]["port"],
            exc,
        )
        return 5

    stop_requested = threading.Event()

    def request_shutdown(signum: int, _frame: object) -> None:
        if stop_requested.is_set():
            return
        stop_requested.set()
        LOGGER.info("Signal %s reçu, arrêt du service…", signum)
        # shutdown() must not run in the thread executing serve_forever().
        threading.Thread(target=server.shutdown, name="http-shutdown", daemon=True).start()

    for name in ("SIGTERM", "SIGINT"):
        sig = getattr(signal, name, None)
        if sig is not None:
            try:
                signal.signal(sig, request_shutdown)
            except ValueError:
                pass

    app.start_background()
    LOGGER.info(
        "Service prêt sur http://%s:%s",
        config["server"]["host"],
        config["server"]["port"],
    )
    try:
        server.serve_forever(poll_interval=0.5)
    except KeyboardInterrupt:
        LOGGER.info("Interruption clavier, arrêt.")
    finally:
        server.server_close()
        app.stop_background()
        LOGGER.info("Service arrêté.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
