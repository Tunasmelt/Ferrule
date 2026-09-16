import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / "packages" / "artifact" / "python"))
from ferrule_artifact import canonicalize  # noqa: E402

for fixture in sorted((ROOT / "tests" / "fixtures" / "canonical").glob("*.json")):
    raw = fixture.read_bytes()
    go = subprocess.run(
        ["go", "run", "./packages/artifact/go/cmd/canonicalize"],
        input=raw,
        capture_output=True,
        cwd=ROOT,
        check=True,
        env=os.environ,
    ).stdout
    if canonicalize(raw) != go:
        raise SystemExit(f"conformance mismatch: {fixture.name}")
print("20 Python/Go canonicalization fixtures match")
