from __future__ import annotations

import json
import socket
import threading
from collections.abc import Mapping
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import TracebackType
from typing import cast
from unittest.mock import patch

from .interpreter import run


class FixtureServer:
    def __init__(self, path: Path) -> None:
        self._fixtures = cast(dict[str, object], json.loads(path.read_text(encoding="utf-8")))
        self.requests: list[tuple[str, str]] = []
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:
                host = self.headers.get("Host", "").split(":", 1)[0]
                owner.requests.append((host, self.path))
                key = f"GET {host}{self.path}"
                fixture = cast(Mapping[str, object], owner._fixtures.get(key, {"status": 404, "body": {"error": "fixture not found"}}))
                encoded = json.dumps(fixture.get("body", {}), separators=(",", ":")).encode()
                self.send_response(cast(int, fixture["status"]))
                for name, value in cast(Mapping[str, str], fixture.get("headers", {})).items():
                    self.send_header(name, value)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(encoded)))
                self.end_headers()
                self.wfile.write(encoded)

            def log_message(self, format: str, *args: object) -> None:
                del format, args

        self._server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.port = self._server.server_port
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)

    def __enter__(self) -> FixtureServer:
        self._thread.start()
        return self

    def __exit__(self, exc_type: type[BaseException] | None, exc: BaseException | None, traceback: TracebackType | None) -> None:
        self._server.shutdown()
        self._server.server_close()
        self._thread.join()


def run_mock(plan: object, input_value: dict[str, object], fixture_path: Path) -> dict[str, object]:
    """Execute against fixtures while mapping every DNS lookup to loopback."""
    with FixtureServer(fixture_path) as server:
        def local_address(
            host: str, port: int, family: int = 0, type: int = 0,
            proto: int = 0, flags: int = 0,
        ) -> list[tuple[int, int, int, str, tuple[str, int]]]:
            del host, port, family, type, proto, flags
            return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", server.port))]

        with patch("socket.getaddrinfo", side_effect=local_address):
            return run(plan, input_value)
