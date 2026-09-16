import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).parents[1]


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
        self.assertEqual(1, rejected.returncode, rejected.stderr)
        finding = json.loads(rejected.stdout)
        self.assertEqual("UNDECLARED_HOST", finding["code"])
        self.assertIn("path", finding)


if __name__ == "__main__":
    unittest.main()
