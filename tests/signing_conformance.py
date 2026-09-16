import base64
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / "packages" / "artifact" / "python"))
from ferrule_artifact import build, generate_dev_keypair, sign, verify  # noqa: E402


with tempfile.TemporaryDirectory() as directory:
    temporary = Path(directory)
    executable = temporary / ("artifact.exe" if os.name == "nt" else "artifact")
    subprocess.run(
        ["go", "build", "-o", str(executable), "./packages/artifact/go/cmd/artifact"],
        cwd=ROOT,
        check=True,
    )
    private_key, public_key = generate_dev_keypair()
    private_path = temporary / "private.pem"
    public_path = temporary / "public.pem"
    private_path.write_bytes(private_key)
    public_path.write_bytes(public_key)

    fixtures = sorted((ROOT / "tests" / "fixtures" / "canonical").glob("*.json"))
    if len(fixtures) != 20:
        raise SystemExit(f"got {len(fixtures)} fixtures, want 20")
    for fixture in fixtures:
        artifact = build(fixture.read_bytes())
        python_signature = sign(artifact, private_key)
        subprocess.run(
            [str(executable), "verify", "-key", str(public_path),
             "-signature", base64.b64encode(python_signature).decode("ascii"), str(fixture)],
            cwd=ROOT,
            capture_output=True,
            check=True,
        )
        go_signature = base64.b64decode(
            subprocess.run(
                [str(executable), "sign", "-key", str(private_path), str(fixture)],
                cwd=ROOT,
                capture_output=True,
                check=True,
            ).stdout.strip(),
            validate=True,
        )
        if not verify(artifact, go_signature, public_key):
            raise SystemExit(f"Go signature failed Python verification: {fixture.name}")

print("20 fixtures sign and verify in both Python->Go and Go->Python directions")
