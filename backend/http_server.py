"""Small loopback-only HTTP server for the kiosk UI and local API.

``http.server`` is appropriate here because the service is bound to 127.0.0.1
and serves a single trusted kiosk client with a handful of static assets. It is
not a general-purpose web server: no TLS, no virtual hosts, no reverse proxy
features. The threaded variant keeps one stalled request from blocking polls.
"""

from __future__ import annotations

import json
import logging
import mimetypes
import urllib.parse
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from .dashboard import DashboardApp

MAX_URL_LENGTH = 2048
MAX_STATIC_BYTES = 4 * 1024 * 1024
SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
    "Content-Security-Policy": (
        "default-src 'self'; base-uri 'none'; form-action 'none'; "
        "frame-ancestors 'none'; img-src 'self' data:; "
        "style-src 'self'; script-src 'self'; connect-src 'self'; "
        "font-src 'self'; object-src 'none'"
    ),
}
MIME_OVERRIDES = {
    ".html": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".svg": "image/svg+xml",
    ".json": "application/json; charset=utf-8",
    ".webmanifest": "application/manifest+json",
    ".ico": "image/x-icon",
    ".woff2": "font/woff2",
    ".png": "image/png",
    ".webp": "image/webp",
}


def create_server(
    app: DashboardApp,
    frontend_dir: Path | str,
    host: str,
    port: int,
) -> ThreadingHTTPServer:
    """Create (but do not start) the loopback HTTP server."""

    root = Path(frontend_dir).resolve()

    class Handler(BaseHTTPRequestHandler):
        server_version = "PiDashboard"
        sys_version = ""
        protocol_version = "HTTP/1.1"
        timeout = 15

        def version_string(self) -> str:
            return self.server_version

        def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
            app.logger.debug("HTTP %s - %s", self.address_string(), format % args)

        # -- response helpers -------------------------------------------------
        def _base_headers(self) -> None:
            for name, value in SECURITY_HEADERS.items():
                self.send_header(name, value)
            self.send_header("Cache-Control", "no-store")

        def _send_bytes(
            self,
            status: int,
            body: bytes,
            content_type: str,
            *,
            head: bool = False,
            extra_headers: dict[str, str] | None = None,
        ) -> None:
            self.send_response(status)
            self._base_headers()
            if extra_headers:
                for name, value in extra_headers.items():
                    self.send_header(name, value)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            if not head:
                try:
                    self.wfile.write(body)
                except (BrokenPipeError, ConnectionResetError):
                    pass

        def _send_json(
            self,
            status: int,
            payload: dict[str, Any],
            *,
            head: bool = False,
            extra_headers: dict[str, str] | None = None,
        ) -> None:
            body = json.dumps(
                payload, ensure_ascii=False, separators=(",", ":")
            ).encode("utf-8")
            self._send_bytes(
                status,
                body,
                "application/json; charset=utf-8",
                head=head,
                extra_headers=extra_headers,
            )

        def _not_found(self, *, json_response: bool, head: bool = False) -> None:
            if json_response:
                self._send_json(
                    HTTPStatus.NOT_FOUND,
                    {"error": "not_found", "message": "Ressource introuvable."},
                    head=head,
                )
            else:
                self._send_bytes(
                    HTTPStatus.NOT_FOUND,
                    "Ressource introuvable.\n".encode("utf-8"),
                    "text/plain; charset=utf-8",
                    head=head,
                )

        # -- routing ----------------------------------------------------------
        def do_GET(self) -> None:  # noqa: N802
            self._handle(head=False)

        def do_HEAD(self) -> None:  # noqa: N802
            self._handle(head=True)

        def do_POST(self) -> None:  # noqa: N802
            self._method_not_allowed()

        def do_PUT(self) -> None:  # noqa: N802
            self._method_not_allowed()

        def do_DELETE(self) -> None:  # noqa: N802
            self._method_not_allowed()

        def do_PATCH(self) -> None:  # noqa: N802
            self._method_not_allowed()

        def _method_not_allowed(self) -> None:
            self._send_json(
                HTTPStatus.METHOD_NOT_ALLOWED,
                {"error": "method_not_allowed", "message": "Méthode non autorisée."},
                head=False,
                extra_headers={"Allow": "GET, HEAD"},
            )

        def _handle(self, *, head: bool) -> None:
            if len(self.path) > MAX_URL_LENGTH:
                self._send_json(
                    HTTPStatus.REQUEST_URI_TOO_LONG,
                    {"error": "uri_too_long", "message": "URI trop longue."},
                    head=head,
                )
                return
            try:
                parsed = urllib.parse.urlsplit(self.path)
            except ValueError:
                self._send_json(
                    HTTPStatus.BAD_REQUEST,
                    {"error": "bad_request", "message": "Requête invalide."},
                    head=head,
                )
                return

            path = urllib.parse.unquote(parsed.path)
            if path == "/api/status":
                try:
                    self._send_json(HTTPStatus.OK, app.status(), head=head)
                except Exception:
                    app.logger.exception("Erreur lors de la construction de /api/status")
                    self._send_json(
                        HTTPStatus.INTERNAL_SERVER_ERROR,
                        {
                            "error": "internal_error",
                            "message": "Erreur interne du service.",
                        },
                        head=head,
                    )
                return

            if path == "/health":
                try:
                    self._send_json(HTTPStatus.OK, app.health(), head=head)
                except Exception:
                    app.logger.exception("Erreur lors de la construction de /health")
                    self._send_json(
                        HTTPStatus.INTERNAL_SERVER_ERROR,
                        {
                            "error": "internal_error",
                            "message": "Erreur interne du service.",
                        },
                        head=head,
                    )
                return

            if path.startswith("/api/"):
                self._not_found(json_response=True, head=head)
                return

            if path == "/favicon.ico":
                path = "/assets/img/favicon.svg"
            self._serve_static(path, head=head)

        def _serve_static(self, path: str, *, head: bool) -> None:
            if "\x00" in path:
                self._not_found(json_response=False, head=head)
                return
            relative = path.lstrip("/")
            if path.endswith("/"):
                relative = f"{relative}index.html"
            if not relative:
                relative = "index.html"

            candidate = (root / relative).resolve()
            try:
                candidate.relative_to(root)
            except ValueError:
                self._not_found(json_response=False, head=head)
                return
            if not candidate.is_file():
                self._not_found(json_response=False, head=head)
                return
            try:
                if candidate.stat().st_size > MAX_STATIC_BYTES:
                    self._send_bytes(
                        HTTPStatus.REQUEST_ENTITY_TOO_LARGE,
                        b"Ressource trop volumineuse.\n",
                        "text/plain; charset=utf-8",
                        head=head,
                    )
                    return
                body = candidate.read_bytes()
            except OSError:
                app.logger.exception("Lecture impossible de %s", candidate)
                self._send_json(
                    HTTPStatus.INTERNAL_SERVER_ERROR,
                    {"error": "internal_error", "message": "Erreur interne du service."},
                    head=head,
                )
                return

            suffix = candidate.suffix.lower()
            content_type = MIME_OVERRIDES.get(suffix)
            if content_type is None:
                content_type = mimetypes.guess_type(candidate.name)[0] or "application/octet-stream"
                if content_type.startswith("text/"):
                    content_type += "; charset=utf-8"
            self._send_bytes(
                HTTPStatus.OK,
                body,
                content_type,
                head=head,
            )

    class Server(ThreadingHTTPServer):
        daemon_threads = True
        allow_reuse_address = True
        request_queue_size = 8

    return Server((host, port), Handler)
