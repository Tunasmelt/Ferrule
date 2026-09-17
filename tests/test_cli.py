import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).parents[1]
for package_path in (
    ROOT / "cli",
    ROOT / "packages" / "artifact" / "python",
    ROOT / "packages" / "plan-schema" / "python",
    ROOT / "packages" / "interpreter" / "python",
):
    sys.path.insert(0, str(package_path))

from ferrule_cli.__main__ import main  # noqa: E402


class CLITests(unittest.TestCase):
    def run_cli(
        self, *arguments: str, input_bytes: bytes | None = None
    ) -> subprocess.CompletedProcess[bytes]:
        env = os.environ.copy()
        env["PYTHONPATH"] = os.pathsep.join(
            [
                str(ROOT / "cli"),
                str(ROOT / "packages" / "artifact" / "python"),
                str(ROOT / "packages" / "plan-schema" / "python"),
                str(ROOT / "packages" / "interpreter" / "python"),
            ]
        )
        return subprocess.run(
            [sys.executable, "-m", "ferrule_cli", *arguments],
            input=input_bytes,
            capture_output=True,
            cwd=ROOT,
            env=env,
            check=False,
        )

    def test_canonicalize_prints_bytes(self) -> None:
        result = self.run_cli(
            "artifact", "canonicalize", input_bytes='{"z": 1.0, "a": "é"}'.encode()
        )
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual(b'{"a":"\xc3\xa9","z":1}\n', result.stdout)

    def test_build_hash_sign_verify_commands(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            key_directory = Path(directory) / "keys"
            keygen = self.run_cli("artifact", "keygen", "--directory", str(key_directory))
            self.assertEqual(0, keygen.returncode, keygen.stderr)
            manifest = (
                ROOT
                / "tests"
                / "fixtures"
                / "canonical"
                / "13-manifest-identity.json"
            )
            built = self.run_cli("artifact", "build", str(manifest))
            hashed = self.run_cli("artifact", "hash", str(manifest))
            signed = self.run_cli(
                "artifact",
                "sign",
                str(manifest),
                "--private-key",
                str(key_directory / "dev-private.pem"),
            )
            signature_path = Path(directory) / "signature.txt"
            signature_path.write_bytes(signed.stdout)
            verified = self.run_cli(
                "artifact", "verify", str(manifest),
                "--signature", str(signature_path),
                "--public-key", str(key_directory / "dev-public.pem"),
            )
            self.assertEqual(0, built.returncode, built.stderr)
            self.assertTrue(hashed.stdout.startswith(b"sha256:"))
            self.assertEqual(0, signed.returncode, signed.stderr)
            self.assertEqual([b"verified"], verified.stdout.splitlines())

            signature_path.write_text("truncated", encoding="ascii")
            rejected = self.run_cli(
                "artifact", "verify", str(manifest),
                "--signature", str(signature_path),
                "--public-key", str(key_directory / "dev-public.pem"),
            )
            self.assertEqual(1, rejected.returncode)
            self.assertIn(b"verification failed", rejected.stderr)

    def test_keygen_creates_new_keypair_with_restricted_private_key(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            key_directory = Path(directory) / "keys"
            result = self.run_cli("artifact", "keygen", "--directory", str(key_directory))
            self.assertEqual(0, result.returncode, result.stderr)
            self.assertTrue((key_directory / "dev-private.pem").is_file())
            self.assertTrue((key_directory / "dev-public.pem").is_file())
            if os.name != "nt":
                # Windows reports mode bits but ACLs, not chmod-style bits, enforce access.
                self.assertEqual(0o600, (key_directory / "dev-private.pem").stat().st_mode & 0o777)
                self.assertEqual(0o644, (key_directory / "dev-public.pem").stat().st_mode & 0o777)

    def test_keygen_refuses_to_overwrite_existing_private_key(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            key_directory = Path(directory)
            private_path = key_directory / "dev-private.pem"
            private_path.write_bytes(b"existing private key")
            result = self.run_cli("artifact", "keygen", "--directory", str(key_directory))
            self.assertEqual(2, result.returncode)
            self.assertIn(b"refusing to overwrite an existing dev keypair", result.stderr)
            self.assertEqual(b"existing private key", private_path.read_bytes())
            self.assertFalse((key_directory / "dev-public.pem").exists())

    def test_keygen_atomic_create_closes_exists_check_race(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            private_path = Path(directory) / "dev-private.pem"
            private_path.write_bytes(b"race winner")
            arguments = ["ferrule", "artifact", "keygen", "--directory", directory]
            with mock.patch.object(sys, "argv", arguments), mock.patch.object(
                Path, "exists", return_value=False
            ), self.assertRaises(SystemExit) as raised:
                main()
            self.assertEqual(2, raised.exception.code)
            self.assertEqual(b"race winner", private_path.read_bytes())

    def test_keygen_removes_private_key_when_public_create_fails(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            key_directory = Path(directory)
            public_path = key_directory / "dev-public.pem"
            public_path.write_bytes(b"existing public key")
            result = self.run_cli("artifact", "keygen", "--directory", str(key_directory))
            self.assertEqual(2, result.returncode)
            self.assertIn(b"refusing to overwrite an existing dev keypair", result.stderr)
            self.assertFalse((key_directory / "dev-private.pem").exists())
            self.assertEqual(b"existing public key", public_path.read_bytes())

    def test_diff_is_stable_human_readable_json(self) -> None:
        fixtures = ROOT / "tests" / "fixtures" / "diff"
        arguments = (
            "artifact",
            "diff",
            str(fixtures / "03-plan-url-old.json"),
            str(fixtures / "03-plan-url-new.json"),
        )
        first = self.run_cli(*arguments)
        second = self.run_cli(*arguments)
        self.assertEqual(0, first.returncode, first.stderr)
        self.assertEqual(first.stdout, second.stdout)
        self.assertIn(b'  "plan_changes": [', first.stdout)
        self.assertIn(b'"field": "url"', first.stdout)

    def test_plan_check_emits_json_lines_and_status(self) -> None:
        fixtures = ROOT / "tests" / "fixtures" / "plans"
        accepted = self.run_cli("plan", "check", str(fixtures / "valid" / "none.json"))
        rejected = self.run_cli(
            "plan", "check", str(fixtures / "invalid" / "undeclared-host.json")
        )
        self.assertEqual(0, accepted.returncode, accepted.stderr)
        self.assertEqual(b"", accepted.stdout)
        self.assertIn(b'"plan_coverage": "representable"', accepted.stderr)
        self.assertEqual(1, rejected.returncode, rejected.stderr)
        finding = json.loads(rejected.stdout)
        self.assertEqual("UNDECLARED_HOST", finding["code"])
        self.assertIn("path", finding)

    def test_plan_run_mock_accepts_inline_input(self) -> None:
        fixtures = ROOT / "tests" / "fixtures"
        result = self.run_cli(
            "plan", "run-mock",
            str(fixtures / "plans" / "execution" / "github-repo.json"),
            "--input", '{"owner":"octo","repo":"demo"}',
            "--fixtures", str(fixtures / "http.json"),
        )
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual("ok", json.loads(result.stdout)["route"])


if __name__ == "__main__":
    unittest.main()
