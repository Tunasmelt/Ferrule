import argparse
import sys

from ferrule_artifact import CanonicalizationError, canonicalize


def main() -> int:
    parser = argparse.ArgumentParser(prog="ferrule")
    commands = parser.add_subparsers(dest="command", required=True)
    artifact = commands.add_parser("artifact")
    artifact_commands = artifact.add_subparsers(dest="artifact_command", required=True)
    canonicalize_parser = artifact_commands.add_parser("canonicalize")
    canonicalize_parser.add_argument("file", nargs="?", type=argparse.FileType("rb"), default=sys.stdin.buffer)
    args = parser.parse_args()
    try:
        sys.stdout.buffer.write(canonicalize(args.file.read()) + b"\n")
    except CanonicalizationError as error:
        parser.error(str(error))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
