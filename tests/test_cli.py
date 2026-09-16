import os
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).parents[1]


class CLITests(unittest.TestCase):
    def test_canonicalize_prints_bytes(self) -> None:
        env = os.environ.copy()
        env["PYTHONPATH"] = os.pathsep.join(
            [str(ROOT / "cli"), str(ROOT / "packages" / "artifact" / "python")]
        )
        result = subprocess.run(
            [sys.executable, "-m", "ferrule_cli", "artifact", "canonicalize"],
            input='{"z": 1.0, "a": "é"}'.encode(),
            capture_output=True,
            cwd=ROOT,
            env=env,
            check=True,
        )
        self.assertEqual(b'{"a":"\xc3\xa9","z":1}\n', result.stdout)


if __name__ == "__main__":
    unittest.main()
