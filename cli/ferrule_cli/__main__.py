import argparse
import json
import sys
from pathlib import Path

from ferrule_artifact import (
    CanonicalizationError,
    artifact_hash,
    build,
    decode_signature,
    diff,
    encode_signature,
    generate_dev_keypair,
    sign,
    verify,
)
from ferrule_plan_schema import check


def _input(path: Path | None) -> bytes:
    return path.read_bytes() if path else sys.stdin.buffer.read()


def main() -> int:
    parser = argparse.ArgumentParser(prog="ferrule")
    commands = parser.add_subparsers(dest="command", required=True)
    artifact = commands.add_parser("artifact")
    subcommands = artifact.add_subparsers(dest="artifact_command", required=True)

    for name in ("canonicalize", "build", "hash"):
        command = subcommands.add_parser(name)
        command.add_argument("file", nargs="?", type=Path)

    sign_parser = subcommands.add_parser("sign")
    sign_parser.add_argument("file", nargs="?", type=Path)
    sign_parser.add_argument("--private-key", required=True, type=Path)

    verify_parser = subcommands.add_parser("verify")
    verify_parser.add_argument("file", nargs="?", type=Path)
    verify_parser.add_argument("--signature", required=True, type=Path)
    verify_parser.add_argument("--public-key", required=True, type=Path)

    keygen_parser = subcommands.add_parser("keygen")
    keygen_parser.add_argument("--directory", type=Path, default=Path(".ferrule/keys"))

    diff_parser = subcommands.add_parser("diff")
    diff_parser.add_argument("old_file", type=Path)
    diff_parser.add_argument("new_file", type=Path)

    plan = commands.add_parser("plan")
    plan_commands = plan.add_subparsers(dest="plan_command", required=True)
    plan_check = plan_commands.add_parser("check")
    plan_check.add_argument("file", type=Path)

    args = parser.parse_args()
    try:
        if args.command == "plan":
            document: object = json.loads(args.file.read_text(encoding="utf-8"))
            findings = check(document)
            for finding in findings:
                print(json.dumps(vars(finding), sort_keys=True))
            return 1 if findings else 0

        if args.artifact_command == "keygen":
            args.directory.mkdir(parents=True, exist_ok=True)
            private_path = args.directory / "dev-private.pem"
            public_path = args.directory / "dev-public.pem"
            if private_path.exists() or public_path.exists():
                parser.error("refusing to overwrite an existing dev keypair")
            private_key, public_key = generate_dev_keypair()
            private_path.write_bytes(private_key)
            private_path.chmod(0o600)
            public_path.write_bytes(public_key)
            print(f"development-only keypair written to {args.directory}")
            return 0

        if args.artifact_command == "diff":
            print(
                json.dumps(
                    diff(args.old_file.read_bytes(), args.new_file.read_bytes()),
                    indent=2,
                    sort_keys=True,
                )
            )
            return 0

        raw = _input(args.file)
        if args.artifact_command in ("canonicalize", "build"):
            sys.stdout.buffer.write(build(raw) + b"\n")
        elif args.artifact_command == "hash":
            print(artifact_hash(build(raw)))
        elif args.artifact_command == "sign":
            signature = sign(build(raw), args.private_key.read_bytes())
            print(encode_signature(signature))
        elif args.artifact_command == "verify":
            encoded = args.signature.read_text(encoding="ascii").strip()
            decoded_signature = decode_signature(encoded)
            if decoded_signature is None or not verify(
                build(raw), decoded_signature, args.public_key.read_bytes()
            ):
                print("verification failed", file=sys.stderr)
                return 1
            print("verified")
    except (CanonicalizationError, OSError, TypeError, ValueError) as error:
        parser.error(str(error))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
