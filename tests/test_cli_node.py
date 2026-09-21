import contextlib
import io
import json
import socket
import sys
import threading
import time
import unittest
from pathlib import Path

import httpx
import uvicorn

ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / "services" / "compiler" / "python"))
sys.path.insert(0, str(ROOT / "cli"))

from ferrule_cli.__main__ import main as cli_main  # noqa: E402
from ferrule_compiler.api import create_app  # noqa: E402


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


class CLINodeTests(unittest.TestCase):
    """Exercises `ferrule node review/verify/approve` against a real, running
    compiler service (uvicorn in a background thread) -- these commands are
    only meaningful as real HTTP calls, so no in-process shortcut proves
    what actually matters here: that the CLI, the ASGI app, and phase-0's
    signature verification all genuinely interoperate.
    """

    @classmethod
    def setUpClass(cls) -> None:
        cls.port = _free_port()
        cls.base_url = f"http://127.0.0.1:{cls.port}"
        config = uvicorn.Config(create_app(), host="127.0.0.1", port=cls.port, log_level="warning")
        cls.server = uvicorn.Server(config)
        cls.thread = threading.Thread(target=cls.server.run, daemon=True)
        cls.thread.start()
        deadline = time.time() + 10
        while not cls.server.started and time.time() < deadline:
            time.sleep(0.05)
        if not cls.server.started:
            raise RuntimeError("uvicorn server did not start in time")

    @classmethod
    def tearDownClass(cls) -> None:
        cls.server.should_exit = True
        cls.thread.join(timeout=5)

    def _run_cli(self, argv: list[str]) -> tuple[int, str]:
        stdout = io.StringIO()
        old_argv = sys.argv
        sys.argv = ["ferrule", *argv]
        try:
            with contextlib.redirect_stdout(stdout):
                exit_code = cli_main()
        except SystemExit as error:
            exit_code = error.code if isinstance(error.code, int) else 1
        finally:
            sys.argv = old_argv
        return exit_code, stdout.getvalue()

    def _register_and_compile(self) -> tuple[str, str]:
        with httpx.Client(base_url=self.base_url, timeout=10.0) as client:
            source = client.post(
                "/sources", json={"name": "gh", "base_url": "https://api.github.com", "auth_kind": "bearer"}
            ).json()
            fixture = ROOT / "tests" / "fixtures" / "openapi" / "github.json"
            with fixture.open("rb") as file:
                client.post(
                    f"/sources/{source['id']}/documents",
                    data={"kind": "openapi"},
                    files={"file": (fixture.name, file, "application/json")},
                )
            client.post(f"/sources/{source['id']}/extract")
            compiled = client.post(
                "/nodes/compile",
                json={"source_id": source["id"], "task": "Get a repository given its owner and repo"},
            ).json()
        _, node_id, _, semver, _ = compiled["evidence_url"].strip("/").split("/")
        return node_id, semver

    def test_review_prints_human_readable_evidence(self) -> None:
        node_id, semver = self._register_and_compile()
        code, output = self._run_cli(["node", "review", node_id, semver, "--base-url", self.base_url])
        self.assertEqual(0, code)
        self.assertIn("Status: proposed", output)
        self.assertIn("Behaviour:", output)
        self.assertIn("Capabilities:", output)
        self.assertIn("Assumptions:", output)
        self.assertIn("Verification:", output)

    def test_verify_before_approval_reports_not_approved(self) -> None:
        node_id, semver = self._register_and_compile()
        code, _output = self._run_cli(["node", "verify", node_id, semver, "--base-url", self.base_url])
        self.assertEqual(1, code)

    def test_approve_then_verify_succeeds(self) -> None:
        node_id, semver = self._register_and_compile()
        approve_code, approve_output = self._run_cli(
            ["node", "approve", node_id, semver, "--reviewer-note", "looks fine", "--base-url", self.base_url]
        )
        self.assertEqual(0, approve_code)
        approved_body = json.loads(approve_output)
        self.assertEqual("approved", approved_body["status"])

        verify_code, verify_output = self._run_cli(["node", "verify", node_id, semver, "--base-url", self.base_url])
        self.assertEqual(0, verify_code)
        self.assertIn("verified", verify_output)

    def test_review_of_unknown_node_fails_cleanly(self) -> None:
        with self.assertRaises(SystemExit):
            self._run_cli_raising(["node", "review", "nd_missing", "1.0.0", "--base-url", self.base_url])

    def _run_cli_raising(self, argv: list[str]) -> None:
        old_argv = sys.argv
        sys.argv = ["ferrule", *argv]
        try:
            cli_main()
        finally:
            sys.argv = old_argv


if __name__ == "__main__":
    unittest.main()
