import base64
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / "packages" / "artifact" / "python"))

from ferrule_artifact import (  # noqa: E402
    artifact_hash,
    build,
    generate_dev_keypair,
    sign,
    verify,
)


class ArtifactTests(unittest.TestCase):
    def setUp(self) -> None:
        self.fixtures = sorted((ROOT / "tests" / "fixtures" / "canonical").glob("*.json"))
        self.assertEqual(20, len(self.fixtures))
        self.private_key, self.public_key = generate_dev_keypair()

    def test_all_fixtures_build_sign_verify(self) -> None:
        for fixture in self.fixtures:
            artifact = build(fixture.read_bytes())
            signature = sign(artifact, self.private_key)
            self.assertTrue(verify(artifact, signature, self.public_key), fixture.name)
            self.assertEqual(64, len(signature))
            self.assertTrue(artifact_hash(artifact).startswith("sha256:"))

    def test_mutation_and_cross_artifact_reuse_fail(self) -> None:
        first = build(self.fixtures[12].read_bytes())
        second = build(self.fixtures[13].read_bytes())
        signature = sign(first, self.private_key)
        for index in range(len(first)):
            mutated = bytearray(first)
            mutated[index] ^= 1
            self.assertFalse(verify(bytes(mutated), signature, self.public_key))
        self.assertFalse(verify(second, signature, self.public_key))

    def test_malformed_signatures_fail_closed(self) -> None:
        artifact = build(self.fixtures[0].read_bytes())
        signature = sign(artifact, self.private_key)
        for malformed in (b"", signature[:-1], signature + b"x", b"x" * 64):
            with self.subTest(length=len(malformed)):
                self.assertFalse(verify(artifact, malformed, self.public_key))
        self.assertFalse(verify(artifact, signature, b"not a public key"))

    def test_dev_keypair_can_be_written_without_committing_private_key(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            private_path = Path(directory) / "dev-private.pem"
            public_path = Path(directory) / "dev-public.pem"
            private_path.write_bytes(self.private_key)
            public_path.write_bytes(self.public_key)
            signature = sign(b"{}", private_path.read_bytes())
            self.assertTrue(verify(b"{}", signature, public_path.read_bytes()))
            self.assertEqual(signature, base64.b64decode(base64.b64encode(signature)))

    def test_default_dev_private_key_is_gitignored(self) -> None:
        ignored = subprocess.run(
            ["git", "check-ignore", "--quiet", ".ferrule/keys/dev-private.pem"],
            cwd=ROOT,
            check=False,
        )
        self.assertEqual(0, ignored.returncode)


if __name__ == "__main__":
    unittest.main()
