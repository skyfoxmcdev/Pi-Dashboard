from __future__ import annotations

import http.client
import json
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from backend.dashboard import DashboardApp
from backend.http_server import create_server
from backend.network import NetworkInfo
from backend.system_metrics import SystemMetrics
from backend.weather import WeatherService
from tests.helpers import ROOT, make_config


class ServerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.tmp_path = Path(self.tmp.name)
        self.config = make_config(self.tmp_path)
        self.config["location"]["latitude"] = None
        self.config["location"]["longitude"] = None
        self.config["night_mode"] = {"enabled": True, "start": "22:00", "end": "07:00"}

        empty_root = self.tmp_path / "empty-root"
        empty_root.mkdir()
        weather = WeatherService(self.config)
        metrics = SystemMetrics(self.config["system"], root=empty_root, clock=lambda: 0.0)
        network = NetworkInfo(
            root=empty_root,
            cache_seconds=0,
            runner=lambda args: None,
            ip_reader=lambda: "192.168.1.50",
        )
        self.app = DashboardApp(
            self.config,
            ROOT / "frontend",
            weather=weather,
            metrics=metrics,
            network=network,
            now=lambda: datetime(2026, 10, 28, 23, 30, tzinfo=timezone.utc),
        )
        self.server = create_server(
            self.app, ROOT / "frontend", "127.0.0.1", 0
        )
        self.port = self.server.server_address[1]
        self.thread = threading.Thread(
            target=self.server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True
        )
        self.thread.start()
        self.base = f"http://127.0.0.1:{self.port}"

    def tearDown(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)
        self.app.stop_background()
        self.tmp.cleanup()

    def get(self, path: str) -> tuple[int, dict, bytes]:
        try:
            with urllib.request.urlopen(self.base + path, timeout=3) as response:
                return response.status, dict(response.headers), response.read()
        except urllib.error.HTTPError as error:
            try:
                return error.code, dict(error.headers), error.read()
            finally:
                error.close()

    def test_health_endpoint(self) -> None:
        status, headers, body = self.get("/health")
        payload = json.loads(body)
        self.assertEqual(status, 200)
        self.assertEqual(payload["status"], "ok")
        self.assertEqual(payload["service"], "Pi Dashboard")
        self.assertIn("uptime_seconds", payload)
        self.assertIn("application/json", headers["Content-Type"])

    def test_status_endpoint_contract(self) -> None:
        status, headers, body = self.get("/api/status")
        payload = json.loads(body)
        self.assertEqual(status, 200)
        self.assertIn("default-src 'self'", headers["Content-Security-Policy"])
        self.assertEqual(headers["X-Content-Type-Options"], "nosniff")
        self.assertEqual(headers["Cache-Control"], "no-store")
        for key in ("app", "generated_at", "location", "night", "weather", "system", "network", "ui"):
            self.assertIn(key, payload)
        self.assertEqual(payload["app"]["name"], "Pi Dashboard")
        self.assertEqual(payload["app"]["version"], "1.1.0")
        self.assertEqual(payload["weather"]["state"], "unconfigured")
        self.assertIsNone(payload["weather"]["current"])
        self.assertTrue(payload["night"]["active"])
        self.assertEqual(payload["night"]["start"], "22:00")
        self.assertEqual(payload["network"]["ip_address"], "192.168.1.50")
        self.assertIn("Coordonnées", body.decode("utf-8"))

    def test_index_and_assets_are_served_locally(self) -> None:
        status, headers, body = self.get("/")
        self.assertEqual(status, 200)
        self.assertIn("text/html", headers["Content-Type"])
        self.assertIn("Pi Dashboard", body.decode("utf-8"))
        self.assertIn(b"/assets/js/app.js", body)

        status, headers, body = self.get("/assets/css/style.css")
        self.assertEqual(status, 200)
        self.assertIn("text/css", headers["Content-Type"])
        self.assertIn(b"Dark Ambient", body)

        status, headers, _body = self.get("/favicon.ico")
        self.assertEqual(status, 200)
        self.assertEqual(headers["Content-Type"], "image/svg+xml")

    def test_missing_file_and_unknown_api_are_404(self) -> None:
        status, _headers, body = self.get("/assets/missing.png")
        self.assertEqual(status, 404)
        self.assertIn(b"introuvable", body)

        status, headers, body = self.get("/api/unknown")
        self.assertEqual(status, 404)
        self.assertIn("application/json", headers["Content-Type"])
        self.assertEqual(json.loads(body)["error"], "not_found")

    def test_directory_traversal_is_blocked(self) -> None:
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=3)
        for path in (
            "/../config/config.example.json",
            "/%2e%2e/config/config.example.json",
            "/assets/../../backend/config.py",
        ):
            connection.request("GET", path)
            response = connection.getresponse()
            body = response.read()
            self.assertEqual(response.status, 404, path)
            self.assertNotIn(b"provider", body)
        connection.close()

    def test_head_has_headers_but_no_body(self) -> None:
        request = urllib.request.Request(self.base + "/health", method="HEAD")
        with urllib.request.urlopen(request, timeout=3) as response:
            self.assertEqual(response.status, 200)
            self.assertGreater(int(response.headers["Content-Length"]), 0)
            self.assertEqual(response.read(), b"")

    def test_post_is_rejected(self) -> None:
        request = urllib.request.Request(self.base + "/api/status", data=b"x", method="POST")
        with self.assertRaises(urllib.error.HTTPError) as context:
            urllib.request.urlopen(request, timeout=3)
        try:
            self.assertEqual(context.exception.code, 405)
        finally:
            context.exception.close()

    def test_malformed_encoded_path_is_not_served(self) -> None:
        status, _headers, _body = self.get("/assets/%00evil.js")
        self.assertEqual(status, 404)


class DashboardAppTests(unittest.TestCase):
    def test_health_and_status_use_injected_components(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            config = make_config(tmp_path)
            config["location"]["latitude"] = None
            config["location"]["longitude"] = None
            empty_root = tmp_path / "empty"
            empty_root.mkdir()
            app = DashboardApp(
                config,
                ROOT / "frontend",
                weather=WeatherService(config),
                metrics=SystemMetrics(config["system"], root=empty_root),
                network=NetworkInfo(
                    root=empty_root,
                    runner=lambda args: None,
                    ip_reader=lambda: "10.0.0.5",
                ),
            )
            status = app.status()
            self.assertEqual(status["network"]["ip_address"], "10.0.0.5")
            self.assertEqual(status["weather"]["state"], "unconfigured")
            self.assertEqual(status["night"]["enabled"], True)
            self.assertIn("version", app.health())


if __name__ == "__main__":
    unittest.main()
