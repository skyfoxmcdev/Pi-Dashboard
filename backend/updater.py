"""Automatic updates for Pi Dashboard, driven by GitHub Releases.

The updater is deliberately standalone and uses only the Python standard
library.  A release is installed only after these checks:

* the GitHub repository and release asset names are valid;
* the release archive matches the SHA-256 published in ``SHA256SUMS``;
* the archive is extracted without absolute paths, ``..`` segments or links;
* the version in the archive matches the release tag;
* the project's unit tests and configuration validation pass;
* the backend answers ``/health`` after the restart.

A copy of the previous application tree is kept in
``/var/lib/pi-dashboard/update-backup`` so ``pi-dashboard-update rollback`` can
restore it.  The personal configuration (``/etc/pi-dashboard/config.json``) is
never replaced by an update.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any, Iterator

try:  # pragma: no cover - the updater itself runs on Linux
    import fcntl
except ImportError:  # pragma: no cover - Windows test host
    fcntl = None  # type: ignore[assignment]

from . import __version__

LOGGER = logging.getLogger("pi-dashboard-update")

APP_DIR = Path(os.environ.get("PI_DASHBOARD_APP_DIR", "/opt/pi-dashboard"))
CONFIG_DIR = Path(os.environ.get("PI_DASHBOARD_CONFIG_DIR", "/etc/pi-dashboard"))
STATE_DIR = Path(os.environ.get("PI_DASHBOARD_STATE_DIR", "/var/lib/pi-dashboard"))
UPDATE_CONFIG = CONFIG_DIR / "update.json"
APP_CONFIG = CONFIG_DIR / "config.json"
STATE_FILE = STATE_DIR / "update-state.json"
BACKUP_DIR = STATE_DIR / "update-backup"
LOCK_FILE = STATE_DIR / "update.lock"

SERVICE_NAME = "pi-dashboard.service"
TIMER_NAME = "pi-dashboard-update.timer"
UPDATE_SERVICE_NAME = "pi-dashboard-update.service"

API_ROOT = "https://api.github.com"
ALLOWED_HOSTS = frozenset(
    {
        "api.github.com",
        "github.com",
        "objects.githubusercontent.com",
        "release-assets.githubusercontent.com",
        "codeload.github.com",
    }
)
MAX_JSON_BYTES = 2 * 1024 * 1024
MAX_CHECKSUM_BYTES = 64 * 1024
MAX_ARCHIVE_BYTES = 32 * 1024 * 1024
MAX_EXTRACTED_BYTES = 96 * 1024 * 1024
MAX_ARCHIVE_MEMBERS = 5000
USER_AGENT = f"PiDashboard/{__version__} updater"

REPOSITORY_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
ASSET_PREFIX_RE = re.compile(r"^[A-Za-z0-9._-]+$")
VERSION_RE = re.compile(
    r"^v?(\d+)\.(\d+)\.(\d+)(?:[-+]([0-9A-Za-z.-]+))?$"
)
CHECKSUM_RE = re.compile(r"^([0-9a-fA-F]{64})\s+\*?(.+?)\s*$")
UPDATABLE_DIRS = ("backend", "frontend", "tests", "deploy")
UPDATABLE_FILES = ("README.md", "LICENSE")
EXECUTABLE_SUFFIXES = (".sh",)
EXECUTABLE_NAMES = {"pi-dashboard-update", "pi-dashboard-kiosk"}


class UpdateError(RuntimeError):
    """A user-actionable update failure."""


@dataclass(frozen=True)
class ReleaseInfo:
    tag: str
    version: str
    asset_name: str
    asset_url: str
    checksum_url: str
    html_url: str


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _is_root() -> bool:
    return getattr(os, "geteuid", lambda: 0)() == 0


def parse_version(value: str) -> tuple[int, int, int, int]:
    """Return a comparable key for a stable-ish semantic version tag.

    Pre-releases sort before the corresponding final release.  The updater
    intentionally ignores the pre-release label when choosing an archive name;
    release workflows in this project publish final tags.
    """

    match = VERSION_RE.fullmatch(str(value).strip())
    if not match:
        raise UpdateError(f"version ou tag invalide : {value!r}")
    major, minor, patch = (int(part) for part in match.groups()[:3])
    is_final = 0 if match.group(4) else 1
    return (major, minor, patch, is_final)


def version_from_tag(tag: str) -> str:
    """Return the version without a leading ``v`` and validate the tag."""

    match = VERSION_RE.fullmatch(str(tag).strip())
    if not match:
        raise UpdateError(f"tag de release invalide : {tag!r}")
    return str(tag).strip().lstrip("v")


def is_newer(candidate: str, current: str) -> bool:
    return parse_version(candidate) > parse_version(current)


def release_asset_name(prefix: str, tag: str) -> str:
    if not ASSET_PREFIX_RE.fullmatch(prefix):
        raise UpdateError(f"préfixe d'archive invalide : {prefix!r}")
    return f"{prefix}-{version_from_tag(tag)}.tar.gz"


def parse_checksums(text: str) -> dict[str, str]:
    """Parse a ``sha256sum``-style file into ``{filename: digest}``."""

    result: dict[str, str] = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        match = CHECKSUM_RE.fullmatch(line)
        if not match:
            raise UpdateError("ligne SHA256SUMS invalide")
        digest, filename = match.groups()
        name = PurePosixPath(filename.replace("\\", "/")).name
        if not name:
            raise UpdateError("nom de fichier SHA256SUMS invalide")
        result[name] = digest.lower()
    if not result:
        raise UpdateError("fichier SHA256SUMS vide")
    return result


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _validate_url(url: str, *, purpose: str = "téléchargement") -> None:
    parsed = urllib.parse.urlsplit(url)
    if parsed.scheme != "https":
        raise UpdateError(f"{purpose} non HTTPS refusé : {url}")
    if parsed.hostname not in ALLOWED_HOSTS:
        raise UpdateError(f"hôte {purpose} non autorisé : {parsed.hostname}")
    if parsed.username or parsed.password or parsed.fragment:
        raise UpdateError(f"URL {purpose} invalide")


class _SafeRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # type: ignore[no-untyped-def]
        _validate_url(newurl, purpose="redirection")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


OPENER = urllib.request.build_opener(_SafeRedirectHandler)


def _read_limited(response: Any, limit: int) -> bytes:
    chunks: list[bytes] = []
    total = 0
    while True:
        chunk = response.read(min(65536, limit + 1 - total))
        if not chunk:
            break
        total += len(chunk)
        if total > limit:
            raise UpdateError(f"réponse trop volumineuse (limite {limit} octets)")
        chunks.append(chunk)
    return b"".join(chunks)


def _get(url: str, *, limit: int, accept: str, timeout: int = 30) -> bytes:
    _validate_url(url)
    request = urllib.request.Request(
        url,
        headers={
            "Accept": accept,
            "User-Agent": USER_AGENT,
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )
    try:
        with OPENER.open(request, timeout=timeout) as response:
            _validate_url(response.geturl())
            if response.status != 200:
                raise UpdateError(f"HTTP {response.status} pour {url}")
            declared = response.headers.get("Content-Length")
            if declared and declared.isdigit() and int(declared) > limit:
                raise UpdateError("contenu annoncé trop volumineux")
            return _read_limited(response, limit)
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            raise UpdateError("release GitHub introuvable (dépôt privé ou aucune release publiée)") from exc
        if exc.code in (403, 429):
            raise UpdateError(
                "GitHub limite les requêtes non authentifiées ; réessayez plus tard"
            ) from exc
        raise UpdateError(f"GitHub a répondu HTTP {exc.code}") from exc
    except urllib.error.URLError as exc:
        raise UpdateError(f"réseau indisponible : {exc.reason}") from exc
    except TimeoutError as exc:
        raise UpdateError("délai réseau dépassé") from exc


def download_file(url: str, destination: Path, *, max_bytes: int) -> None:
    """Download an HTTPS release asset with a size limit and atomic rename."""

    _validate_url(url)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(destination.name + ".part")
    request = urllib.request.Request(
        url,
        headers={"Accept": "application/octet-stream", "User-Agent": USER_AGENT},
    )
    try:
        with OPENER.open(request, timeout=30) as response:
            _validate_url(response.geturl())
            if response.status != 200:
                raise UpdateError(f"HTTP {response.status} pour {url}")
            declared = response.headers.get("Content-Length")
            if declared and declared.isdigit() and int(declared) > max_bytes:
                raise UpdateError("archive trop volumineuse")
            total = 0
            with temporary.open("wb") as handle:
                while True:
                    chunk = response.read(65536)
                    if not chunk:
                        break
                    total += len(chunk)
                    if total > max_bytes:
                        raise UpdateError("archive trop volumineuse")
                    handle.write(chunk)
        os.replace(temporary, destination)
    except urllib.error.HTTPError as exc:
        raise UpdateError(f"téléchargement GitHub HTTP {exc.code}") from exc
    except urllib.error.URLError as exc:
        raise UpdateError(f"téléchargement impossible : {exc.reason}") from exc
    except TimeoutError as exc:
        raise UpdateError("délai de téléchargement dépassé") from exc
    finally:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass


def fetch_latest_release(
    repository: str,
    asset_prefix: str = "pi-dashboard",
    *,
    checksum_asset: str = "SHA256SUMS",
    timeout: int = 30,
) -> ReleaseInfo:
    if not REPOSITORY_RE.fullmatch(repository):
        raise UpdateError("update.repository doit être au format proprietaire/depot")
    url = f"{API_ROOT}/repos/{repository}/releases/latest"
    raw = _get(url, limit=MAX_JSON_BYTES, accept="application/vnd.github+json", timeout=timeout)
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise UpdateError("réponse GitHub illisible") from exc
    if not isinstance(payload, dict):
        raise UpdateError("réponse GitHub invalide")
    tag = payload.get("tag_name")
    if not isinstance(tag, str):
        raise UpdateError("release sans tag_name")
    version = version_from_tag(tag)
    expected_asset = release_asset_name(asset_prefix, tag)
    assets_raw = payload.get("assets")
    if not isinstance(assets_raw, list):
        raise UpdateError("release sans liste d'assets")
    assets: dict[str, str] = {}
    for item in assets_raw:
        if not isinstance(item, dict):
            continue
        name = item.get("name")
        download = item.get("browser_download_url")
        if isinstance(name, str) and isinstance(download, str):
            assets[name] = download

    asset_url = assets.get(expected_asset)
    if not asset_url:
        raise UpdateError(f"asset attendu absent de la release : {expected_asset}")
    checksum_name = checksum_asset if checksum_asset in assets else f"{checksum_asset}.txt"
    checksum_url = assets.get(checksum_name)
    if not checksum_url:
        raise UpdateError(f"fichier de contrôle absent : {checksum_asset}")
    html_url = payload.get("html_url")
    return ReleaseInfo(
        tag=tag,
        version=version,
        asset_name=expected_asset,
        asset_url=asset_url,
        checksum_url=checksum_url,
        html_url=html_url if isinstance(html_url, str) else "",
    )


def _safe_target(destination: Path, name: str) -> Path:
    if "\x00" in name or "\\" in name:
        raise UpdateError("chemin d'archive invalide")
    relative = PurePosixPath(name)
    if relative.is_absolute() or not relative.parts:
        raise UpdateError("chemin absolu refusé dans l'archive")
    if any(part in ("", ".", "..") for part in relative.parts):
        raise UpdateError("segment de chemin interdit dans l'archive")
    target = destination.joinpath(*relative.parts)
    resolved = target.resolve(strict=False)
    try:
        resolved.relative_to(destination.resolve())
    except ValueError as exc:
        raise UpdateError("chemin hors du dossier de mise à jour") from exc
    return target


def safe_extract(archive: Path, destination: Path) -> Path:
    """Extract a release archive without links or path traversal.

    Only regular files and directories are accepted.  The archive must contain
    exactly one top-level directory, as produced by ``git archive --prefix``.
    """

    destination = destination.resolve()
    destination.mkdir(parents=True, exist_ok=True)
    try:
        with tarfile.open(archive, "r:gz") as bundle:
            members = bundle.getmembers()
            if not members or len(members) > MAX_ARCHIVE_MEMBERS:
                raise UpdateError("archive vide ou trop nombreuse")
            total = 0
            tops: set[str] = set()
            for member in members:
                target = _safe_target(destination, member.name)
                if member.issym() or member.islnk():
                    raise UpdateError("liens symboliques refusés dans l'archive")
                if not (member.isfile() or member.isdir()):
                    raise UpdateError("type de fichier refusé dans l'archive")
                relative = PurePosixPath(member.name)
                tops.add(relative.parts[0])
                if member.isfile():
                    total += member.size
                    if total > MAX_EXTRACTED_BYTES:
                        raise UpdateError("archive décompressée trop volumineuse")
                    target.parent.mkdir(parents=True, exist_ok=True)
                    source = bundle.extractfile(member)
                    if source is None:
                        raise UpdateError("fichier illisible dans l'archive")
                    with target.open("wb") as handle:
                        shutil.copyfileobj(source, handle, length=65536)
                    mode = 0o755 if member.mode & 0o111 else 0o644
                    target.chmod(mode)
                else:
                    target.mkdir(parents=True, exist_ok=True)
            if len(tops) != 1:
                raise UpdateError("l'archive doit contenir un seul dossier racine")
    except tarfile.TarError as exc:
        raise UpdateError(f"archive tar.gz invalide : {exc}") from exc
    root = destination / next(iter(tops))
    if not root.is_dir():
        raise UpdateError("dossier racine absent de l'archive")
    return root


def read_version_from_tree(root: Path) -> str:
    init = root / "backend" / "__init__.py"
    try:
        text = init.read_text(encoding="utf-8")
    except OSError as exc:
        raise UpdateError("backend/__init__.py absent de la release") from exc
    match = re.search(r'^__version__\s*=\s*["\']([^"\']+)["\']', text, re.MULTILINE)
    if not match:
        raise UpdateError("version introuvable dans backend/__init__.py")
    return match.group(1)


def validate_release_tree(root: Path, expected_version: str) -> None:
    required = (
        "backend/main.py",
        "backend/updater.py",
        "frontend/index.html",
        "deploy/install.sh",
        "deploy/systemd/pi-dashboard.service",
        "tests",
    )
    missing = [name for name in required if not (root / name).exists()]
    if missing:
        raise UpdateError("release incomplète : " + ", ".join(missing))
    actual = read_version_from_tree(root)
    if actual != expected_version:
        raise UpdateError(
            f"version incohérente : release {expected_version}, code {actual}"
        )


def run_checked(command: list[str], *, cwd: Path, timeout: int = 180) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            command,
            cwd=str(cwd),
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout,
            env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
        )
    except FileNotFoundError as exc:
        raise UpdateError(f"commande introuvable : {command[0]}") from exc
    except subprocess.TimeoutExpired as exc:
        raise UpdateError(f"commande trop longue : {' '.join(command)}") from exc


def validate_stage(root: Path, *, config_file: Path | None = None) -> None:
    tests = run_checked([sys.executable, "-m", "unittest", "discover", "-s", "tests", "-q"], cwd=root)
    if tests.returncode != 0:
        detail = (tests.stderr or tests.stdout or "").strip()[-2000:]
        raise UpdateError(f"tests de la release en échec\n{detail}")
    if config_file and config_file.exists():
        config_check = run_checked(
            [sys.executable, "-m", "backend.main", "--config", str(config_file), "--check-config"],
            cwd=root,
        )
        if config_check.returncode != 0:
            detail = (config_check.stderr or config_check.stdout or "").strip()[-2000:]
            raise UpdateError(f"configuration incompatible\n{detail}")


def read_json(path: Path) -> dict[str, Any]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise UpdateError(f"fichier illisible : {path}") from exc
    except json.JSONDecodeError as exc:
        raise UpdateError(f"JSON invalide : {path}") from exc
    if not isinstance(raw, dict):
        raise UpdateError(f"objet JSON attendu : {path}")
    return raw


def write_json_atomic(path: Path, payload: dict[str, Any], mode: int = 0o644) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary_name = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=str(path.parent))
    temporary = Path(temporary_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        temporary.chmod(mode)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def default_update_config() -> dict[str, Any]:
    return {
        "enabled": True,
        "repository": "",
        "channel": "release",
        "asset_prefix": "pi-dashboard",
        "checksum_asset": "SHA256SUMS",
    }


def load_update_config(path: Path = UPDATE_CONFIG) -> dict[str, Any]:
    raw = read_json(path)
    merged = default_update_config()
    merged.update(raw)
    enabled = merged.get("enabled")
    repository = merged.get("repository")
    channel = merged.get("channel")
    prefix = merged.get("asset_prefix")
    checksum = merged.get("checksum_asset")
    if not isinstance(enabled, bool):
        raise UpdateError("update.enabled doit être un booléen")
    if not isinstance(repository, str):
        raise UpdateError("update.repository doit être une chaîne")
    if repository and not REPOSITORY_RE.fullmatch(repository):
        raise UpdateError("update.repository doit être au format proprietaire/depot")
    if channel != "release":
        raise UpdateError("seul le canal release est pris en charge")
    if not isinstance(prefix, str) or not ASSET_PREFIX_RE.fullmatch(prefix):
        raise UpdateError("update.asset_prefix invalide")
    if not isinstance(checksum, str) or not checksum:
        raise UpdateError("update.checksum_asset invalide")
    merged.update(
        enabled=enabled,
        repository=repository,
        channel="release",
        asset_prefix=prefix,
        checksum_asset=checksum,
    )
    return merged


def read_state() -> dict[str, Any]:
    if not STATE_FILE.exists():
        return {}
    try:
        raw = read_json(STATE_FILE)
    except UpdateError:
        return {}
    return raw


def write_state(**values: Any) -> None:
    state = read_state()
    state.update(values)
    state["checked_at"] = _now()
    write_json_atomic(STATE_FILE, state)


@contextmanager
def update_lock() -> Iterator[None]:
    LOCK_FILE.parent.mkdir(parents=True, exist_ok=True)
    with LOCK_FILE.open("a+", encoding="utf-8") as handle:
        if fcntl is None:  # pragma: no cover - Windows tests
            yield
            return
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise UpdateError("une autre mise à jour est déjà en cours") from exc
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def installed_version(app_dir: Path = APP_DIR) -> str:
    try:
        return read_version_from_tree(app_dir)
    except UpdateError:
        return __version__


def _remove_path(path: Path) -> None:
    if path.is_dir() and not path.is_symlink():
        shutil.rmtree(path)
    else:
        path.unlink(missing_ok=True)


def snapshot(app_dir: Path = APP_DIR, backup_dir: Path = BACKUP_DIR) -> None:
    if not app_dir.is_dir():
        raise UpdateError(f"application introuvable : {app_dir}")
    backup_dir.parent.mkdir(parents=True, exist_ok=True)
    temporary = backup_dir.with_name(backup_dir.name + ".new")
    _remove_path(temporary)
    shutil.copytree(
        app_dir,
        temporary,
        symlinks=True,
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc", ".update-*"),
    )
    _remove_path(backup_dir)
    os.replace(temporary, backup_dir)


def _copy_tree_atomic(source: Path, destination: Path, label: str) -> None:
    temporary = destination.with_name(f".update-new-{label}")
    old = destination.with_name(f".update-old-{label}")
    _remove_path(temporary)
    _remove_path(old)
    shutil.copytree(source, temporary, symlinks=False)
    if destination.exists() or destination.is_symlink():
        os.replace(destination, old)
    os.replace(temporary, destination)
    _remove_path(old)


def apply_tree(root: Path, app_dir: Path = APP_DIR) -> None:
    for name in UPDATABLE_DIRS:
        source = root / name
        if not source.is_dir():
            raise UpdateError(f"dossier manquant dans la release : {name}")
        _copy_tree_atomic(source, app_dir / name, name)
    for name in UPDATABLE_FILES:
        source = root / name
        if not source.is_file():
            continue
        temporary = app_dir / f".update-new-{name}"
        _remove_path(temporary)
        shutil.copy2(source, temporary)
        os.replace(temporary, app_dir / name)
    for root_dir, dirnames, filenames in os.walk(app_dir):
        if Path(root_dir) == app_dir / "config":
            dirnames[:] = []
            continue
        for filename in filenames:
            path = Path(root_dir) / filename
            if path.is_symlink():
                continue
            path.chmod(0o755 if path.suffix in EXECUTABLE_SUFFIXES or path.name in EXECUTABLE_NAMES else 0o644)


def restore_backup(app_dir: Path = APP_DIR, backup_dir: Path = BACKUP_DIR) -> None:
    if not backup_dir.is_dir():
        raise UpdateError("aucune sauvegarde de mise à jour disponible")
    for name in UPDATABLE_DIRS:
        source = backup_dir / name
        if source.is_dir():
            _copy_tree_atomic(source, app_dir / name, name)
    for name in UPDATABLE_FILES:
        source = backup_dir / name
        if source.is_file():
            temporary = app_dir / f".update-new-{name}"
            shutil.copy2(source, temporary)
            os.replace(temporary, app_dir / name)


def service_port(config_file: Path = APP_CONFIG) -> int:
    try:
        raw = read_json(config_file)
        value = raw.get("server", {}).get("port", 8080)
        port = int(value)
        return port if 1 <= port <= 65535 else 8080
    except (UpdateError, TypeError, ValueError, AttributeError):
        return 8080


def wait_for_health(port: int, *, timeout: int = 30, expected_version: str | None = None) -> None:
    deadline = time.monotonic() + timeout
    last_error = "aucune réponse"
    url = f"http://127.0.0.1:{port}/health"
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=3) as response:
                if response.status != 200:
                    last_error = f"HTTP {response.status}"
                else:
                    payload = json.loads(response.read(1024 * 1024).decode("utf-8"))
                    version = payload.get("version")
                    if expected_version is None or version == expected_version:
                        return
                    last_error = f"version {version!r} au lieu de {expected_version!r}"
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, UnicodeDecodeError) as exc:
            last_error = str(exc)
        time.sleep(1)
    raise UpdateError(f"/health indisponible après mise à jour : {last_error}")


def restart_service(service: str = SERVICE_NAME) -> None:
    try:
        result = subprocess.run(
            ["systemctl", "restart", service],
            check=False,
            capture_output=True,
            text=True,
            timeout=45,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
        raise UpdateError(f"impossible de redémarrer {service} : {exc}") from exc
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip()
        raise UpdateError(f"échec du redémarrage de {service} : {detail}")


def perform_update(
    *,
    update_config_path: Path = UPDATE_CONFIG,
    config_file: Path = APP_CONFIG,
    app_dir: Path = APP_DIR,
    state_dir: Path = STATE_DIR,
) -> str:
    config = load_update_config(update_config_path)
    if not config["enabled"]:
        LOGGER.info("mise à jour automatique désactivée")
        return "disabled"
    repository = str(config["repository"]).strip()
    if not repository:
        raise UpdateError("update.repository n'est pas configuré")
    current = installed_version(app_dir)
    release = fetch_latest_release(
        repository,
        str(config["asset_prefix"]),
        checksum_asset=str(config["checksum_asset"]),
    )
    if not is_newer(release.version, current):
        LOGGER.info("déjà à jour : version installée %s, dernière release %s", current, release.version)
        write_state(installed_version=current, latest_tag=release.tag, last_result="up-to-date")
        return "up-to-date"

    if not _is_root():
        raise UpdateError("la mise à jour doit être exécutée avec sudo")
    with update_lock():
        state = read_state()
        if state.get("last_result") == "rollback" and state.get("hold"):
            LOGGER.info("mise à jour en attente après un rollback ; utilisez enable")
            return "held"
        state_dir.mkdir(parents=True, exist_ok=True)
        temp_root = Path(tempfile.mkdtemp(prefix="update-", dir=str(state_dir)))
        try:
            archive = temp_root / release.asset_name
            checksums_path = temp_root / "SHA256SUMS"
            LOGGER.info("téléchargement de %s (%s)", release.tag, release.asset_name)
            download_file(release.asset_url, archive, max_bytes=MAX_ARCHIVE_BYTES)
            download_file(release.checksum_url, checksums_path, max_bytes=MAX_CHECKSUM_BYTES)
            checksums = parse_checksums(checksums_path.read_text(encoding="utf-8"))
            expected = checksums.get(release.asset_name)
            if not expected:
                raise UpdateError("l'archive n'est pas référencée dans SHA256SUMS")
            actual = sha256_file(archive)
            if actual != expected:
                raise UpdateError("empreinte SHA-256 incorrecte ; archive refusée")
            stage = safe_extract(archive, temp_root / "extract")
            validate_release_tree(stage, release.version)
            LOGGER.info("validation des tests de la release %s", release.version)
            validate_stage(stage, config_file=config_file)

            snapshot(app_dir, state_dir / "update-backup")
            try:
                apply_tree(stage, app_dir)
                restart_service()
                wait_for_health(service_port(config_file), expected_version=release.version)
            except Exception:
                LOGGER.exception("échec de la release %s, restauration de la version précédente", release.version)
                restore_backup(app_dir, state_dir / "update-backup")
                try:
                    restart_service()
                    wait_for_health(service_port(config_file))
                except Exception:
                    LOGGER.exception("le service n'a pas repris après le rollback")
                raise

            write_state(
                installed_version=release.version,
                installed_tag=release.tag,
                previous_version=current,
                release_url=release.html_url,
                last_result="success",
                hold=False,
            )
            LOGGER.info("mise à jour %s installée", release.version)
            return "updated"
        finally:
            shutil.rmtree(temp_root, ignore_errors=True)


def rollback(
    *,
    update_config_path: Path = UPDATE_CONFIG,
    config_file: Path = APP_CONFIG,
    app_dir: Path = APP_DIR,
    state_dir: Path = STATE_DIR,
) -> None:
    if not _is_root():
        raise UpdateError("le rollback doit être exécuté avec sudo")
    with update_lock():
        backup = state_dir / "update-backup"
        if not backup.is_dir():
            raise UpdateError("aucune sauvegarde disponible")
        previous = installed_version(app_dir)
        restore_backup(app_dir, backup)
        restart_service()
        wait_for_health(service_port(config_file))
        config = load_update_config(update_config_path)
        config["enabled"] = False
        write_json_atomic(update_config_path, config)
        write_state(
            installed_version=installed_version(app_dir),
            previous_version=previous,
            last_result="rollback",
            hold=True,
        )
        LOGGER.info("rollback effectué ; mises à jour automatiques désactivées")
        try:
            subprocess.run(["systemctl", "disable", "--now", TIMER_NAME], check=False, timeout=20)
        except (FileNotFoundError, subprocess.TimeoutExpired):
            pass


def set_enabled(enabled: bool, *, update_config_path: Path = UPDATE_CONFIG) -> None:
    if not _is_root():
        raise UpdateError("cette commande doit être exécutée avec sudo")
    config = load_update_config(update_config_path)
    if not config["repository"]:
        raise UpdateError("update.repository n'est pas configuré")
    config["enabled"] = enabled
    write_json_atomic(update_config_path, config)
    if enabled:
        write_state(hold=False)
    action = "enable" if enabled else "disable"
    try:
        result = subprocess.run(
            ["systemctl", action, "--now", TIMER_NAME],
            check=False,
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode != 0:
            raise UpdateError((result.stderr or result.stdout or "").strip())
    except FileNotFoundError as exc:
        raise UpdateError("systemctl introuvable") from exc
    except subprocess.TimeoutExpired as exc:
        raise UpdateError("systemctl ne répond pas") from exc


def _systemctl_state(unit: str) -> str:
    try:
        result = subprocess.run(
            ["systemctl", "is-active", unit],
            check=False,
            capture_output=True,
            text=True,
            timeout=10,
        )
        return (result.stdout or result.stderr or "inconnu").strip() or "inconnu"
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return "inconnu"


def print_status(*, update_config_path: Path = UPDATE_CONFIG, app_dir: Path = APP_DIR) -> int:
    try:
        config = load_update_config(update_config_path)
    except UpdateError as exc:
        print(f"Configuration : indisponible ({exc})")
        return 1
    state = read_state()
    print(f"Version installée : {installed_version(app_dir)}")
    print(f"Dépôt GitHub      : {config['repository'] or 'non configuré'}")
    print(f"Canal             : {config['channel']}")
    print(f"Automatique       : {'activée' if config['enabled'] else 'désactivée'}")
    print(f"Minuterie         : {_systemctl_state(TIMER_NAME)}")
    if state:
        print(f"Dernière release  : {state.get('installed_tag') or state.get('latest_tag') or '—'}")
        print(f"Dernier contrôle  : {state.get('checked_at', '—')}")
        print(f"Dernier résultat  : {state.get('last_result', '—')}")
    else:
        print("Dernier contrôle  : aucun")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="pi-dashboard-update",
        description="Met à jour Pi Dashboard depuis la dernière release GitHub.",
    )
    sub = parser.add_subparsers(dest="command", required=True)
    run = sub.add_parser("run", help="télécharge et installe la dernière release")
    run.add_argument("--auto", action="store_true", help="mode silencieux utilisé par systemd")
    sub.add_parser("check", help="affiche la dernière release disponible sans rien installer")
    sub.add_parser("status", help="affiche la configuration et le dernier état")
    sub.add_parser("rollback", help="restaure la version précédente et désactive l'auto-update")
    sub.add_parser("enable", help="réactive la minuterie de mise à jour")
    sub.add_parser("disable", help="désactive la minuterie de mise à jour")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
    )
    try:
        if args.command == "status":
            return print_status()
        if args.command == "check":
            config = load_update_config()
            if not config["repository"]:
                raise UpdateError("update.repository n'est pas configuré")
            release = fetch_latest_release(
                str(config["repository"]),
                str(config["asset_prefix"]),
                checksum_asset=str(config["checksum_asset"]),
            )
            current = installed_version()
            print(f"Version installée : {current}")
            print(f"Dernière release  : {release.tag} ({release.html_url or 'URL inconnue'})")
            print("Mise à jour       : " + ("disponible" if is_newer(release.version, current) else "déjà à jour"))
            return 0
        if args.command == "run":
            if not _is_root():
                raise UpdateError("la mise à jour doit être exécutée avec sudo")
            result = perform_update()
            if result == "updated":
                print("Mise à jour installée.")
            elif result == "up-to-date":
                print("Déjà à jour.")
            elif result == "disabled":
                print("Mise à jour automatique désactivée.")
            return 0
        if args.command == "rollback":
            rollback()
            print("Rollback effectué ; auto-update désactivée. Utilisez « sudo pi-dashboard-update enable » pour la réactiver.")
            return 0
        if args.command == "enable":
            set_enabled(True)
            print("Mise à jour automatique activée.")
            return 0
        if args.command == "disable":
            set_enabled(False)
            print("Mise à jour automatique désactivée.")
            return 0
        parser.error("commande inconnue")
    except UpdateError as exc:
        LOGGER.error("%s", exc)
        if args.command == "run" and getattr(args, "auto", False):
            return 1
        return 1
    return 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
