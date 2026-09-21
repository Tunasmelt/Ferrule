import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

import httpx
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
from ferrule_interpreter import PlanRejected, classify_plan
from ferrule_interpreter.mock import run_mock
from ferrule_plan_schema import check


def _input(path: Path | None) -> bytes:
    return path.read_bytes() if path else sys.stdin.buffer.read()


def _write_exclusive(path: Path, contents: bytes, mode: int) -> None:
    descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, mode)
    try:
        with os.fdopen(descriptor, "wb") as output:
            output.write(contents)
    except OSError:
        path.unlink(missing_ok=True)
        raise


def _print_review(evidence: dict[str, Any]) -> None:
    """Human-readable rendering of a GET .../evidence bundle for `ferrule node review`.

    Operates on loosely-typed parsed JSON by design (this is a formatting
    helper over an HTTP response body, not a boundary type in the sense
    CLAUDE.md's "no Any in a public signature" convention means for
    /services and /packages) rather than a full typed mirror of
    ferrule_compiler's Pydantic evidence models.
    """
    print(f"Status: {evidence['status']}")
    print(f"Artifact hash: {evidence['artifact_hash']}")
    print()
    print("Behaviour:")
    print(f"  {evidence['behaviour_summary']}")
    print()
    print("Request preview:")
    for step in evidence["request_preview"]:
        print(f"  [{step['step_id']}] {step['method']} {step['url']}")
        for name, value in step["headers"].items():
            print(f"    header {name}: {value}")
        print(f"    input: {json.dumps(step['rendered_from']['input'], sort_keys=True)}")
    print()
    capabilities = evidence["capabilities"]
    print("Capabilities:")
    print(f"  hosts: {', '.join(capabilities['hosts'])}")
    print(f"  methods: {', '.join(capabilities['methods'])}")
    print(f"  secrets: {', '.join(capabilities['secrets']) or '(none)'}")
    print(f"  egress_default: {capabilities['egress_default']}")
    print(f"  side_effect_profile: {evidence['side_effect_profile']}")
    print()
    print("Assumptions:")
    assumptions = evidence["assumptions"]
    if not assumptions:
        print("  (none)")
    for assumption in assumptions:
        print(f"  - {assumption['claim']}: {assumption['basis']}")
        print(f"    source: {assumption['source_document_id']} span={assumption['source_span']}")
    print()
    print("Verification:")
    verification = evidence["verification"]
    for name in ("static", "mock", "sandbox", "permission"):
        section = verification[name]
        detail = {key: value for key, value in section.items() if key != "passed"}
        print(f"  {name}: passed={section['passed']} {detail}")
    print()
    provenance = evidence["provenance"]
    print("Provenance:")
    print(f"  compiler_version: {provenance['compiler_version']}")
    print(f"  plan_coverage: {provenance['plan_coverage']}")
    print(f"  builder_model: {provenance['builder_model']}")
    print(f"  source_documents: {', '.join(provenance['source_documents'])}")


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
    plan_run = plan_commands.add_parser("run-mock")
    plan_run.add_argument("file", type=Path)
    plan_run.add_argument("--input", required=True)
    plan_run.add_argument("--fixtures", required=True, type=Path)

    node = commands.add_parser("node")
    node_commands = node.add_subparsers(dest="node_command", required=True)
    for node_command_name in ("review", "verify"):
        node_command = node_commands.add_parser(node_command_name)
        node_command.add_argument("node_id")
        node_command.add_argument("semver")
        node_command.add_argument("--base-url", required=True)
    node_approve = node_commands.add_parser("approve")
    node_approve.add_argument("node_id")
    node_approve.add_argument("semver")
    node_approve.add_argument("--base-url", required=True)
    node_approve.add_argument("--reviewer-note", required=True)

    args = parser.parse_args()
    try:
        if args.command == "plan":
            document: object = json.loads(args.file.read_text(encoding="utf-8"))
            if args.plan_command == "run-mock":
                input_path = Path(args.input)
                raw_input = input_path.read_text(encoding="utf-8") if input_path.is_file() else args.input
                input_value = json.loads(raw_input)
                if not isinstance(input_value, dict):
                    raise ValueError("--input must be a JSON object or a file containing one")
                print(json.dumps(run_mock(document, input_value, args.fixtures), sort_keys=True))
                return 0
            findings = check(document)
            print(json.dumps({"plan_coverage": classify_plan(document)}, sort_keys=True), file=sys.stderr)
            for finding in findings:
                print(json.dumps(vars(finding), sort_keys=True))
            return 1 if findings else 0

        if args.command == "node":
            with httpx.Client(base_url=args.base_url, timeout=10.0) as client:
                if args.node_command == "review":
                    response = client.get(f"/nodes/{args.node_id}/versions/{args.semver}/evidence")
                    if response.status_code != 200:
                        parser.error(f"review failed: {response.status_code} {response.text}")
                    _print_review(response.json())
                    return 0
                if args.node_command == "verify":
                    response = client.get(f"/nodes/{args.node_id}/versions/{args.semver}")
                    if response.status_code != 200:
                        parser.error(f"verify failed: {response.status_code} {response.text}")
                    body = response.json()
                    if body["status"] != "approved":
                        print(f"not approved (status={body['status']}); nothing to verify", file=sys.stderr)
                        return 1
                    decoded_signature = decode_signature(body["signature"])
                    if decoded_signature is None or not verify(
                        build(body["plan"]), decoded_signature, body["public_key_pem"].encode("ascii")
                    ):
                        print("verification failed", file=sys.stderr)
                        return 1
                    print("verified")
                    return 0
                # args.node_command == "approve"
                response = client.post(
                    f"/nodes/{args.node_id}/versions/{args.semver}/approve",
                    json={"reviewer_note": args.reviewer_note},
                )
                if response.status_code != 200:
                    parser.error(f"approve failed: {response.status_code} {response.text}")
                body = response.json()
                print(json.dumps(
                    {
                        "node_version_id": body["node_version_id"],
                        "status": body["status"],
                        "artifact_hash": body["artifact_hash"],
                        "approved_at": body["approved_at"],
                    },
                    indent=2,
                    sort_keys=True,
                ))
                return 0

        if args.artifact_command == "keygen":
            args.directory.mkdir(parents=True, exist_ok=True)
            private_path = args.directory / "dev-private.pem"
            public_path = args.directory / "dev-public.pem"
            private_key, public_key = generate_dev_keypair()
            try:
                _write_exclusive(private_path, private_key, 0o600)
            except FileExistsError:
                parser.error("refusing to overwrite an existing dev keypair")
            try:
                _write_exclusive(public_path, public_key, 0o644)
            except OSError as public_error:
                try:
                    private_path.unlink()
                except OSError as cleanup_error:
                    parser.error(
                        f"{public_error}; private key remains at {private_path}: "
                        f"{cleanup_error}"
                    )
                if isinstance(public_error, FileExistsError):
                    parser.error("refusing to overwrite an existing dev keypair")
                raise
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
    except (CanonicalizationError, OSError, PlanRejected, TypeError, ValueError, httpx.HTTPError) as error:
        parser.error(str(error))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
