"""Evidence bundle assembly (milestone 4b), per docs/API.md's
`GET /nodes/{node_id}/versions/{semver}/evidence` shape.

This is the reviewer bundle SPEC.md/API.md describe -- assembled entirely
from data this compiler already has (3a's ingest, 3b's compile, 3c's
claims/mock execution), plus whatever real sandbox/permission results the
caller can supply. Where a field's backing capability genuinely doesn't
exist yet in this codebase (a trace-storage system, an automated per-node
sandbox/permission pipeline), the field is still present -- never silently
omitted -- but honestly reflects "not run" rather than fabricating a
result, matching this project's own stated ethos of never claiming more
than is true.

Two fields are deliberately honest placeholders rather than filled with
plausible-looking values: `provenance.builder_model` and `.prompt_version`
assume an LLM-backed "Builder model" per SPEC.md section 8, which
milestone 3b's own scope decision explicitly does not use (deterministic
template compilation instead) -- inventing a fake provider/model string
here would misrepresent that decision.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Mapping, cast

from ferrule_interpreter import Response, run
from ferrule_interpreter.interpreter import Request

from .claims import Claim
from .generate import CompileResult
from .mocktest import MockTestResult, golden_case, run_mock_case
from .openapi import Operation

# First evidence-bundle-capable version of this compiler (milestone 4b).
# Not the same as the "ferrule" package version in pyproject.toml, which
# tracks the whole monorepo, not this one module's own capability level.
COMPILER_VERSION = "0.4.0"

# Matches packages/plan-schema's own finding categories (SCHEMA_INVALID,
# UNBOUND_TEMPLATE_VARIABLE, CEL_COMPILE_ERROR, UNDECLARED_HOST) under the
# names SPEC.md's own evidence example uses -- this compiler's static
# checker performs exactly these checks, so this is an honest mapping, not
# an aspirational one.
_STATIC_CHECKS = ("schema_valid", "templates_bound", "cel_typechecked", "hosts_declared")

_SECRET_MARKER = re.compile(r"\{\{\s*secret\.([A-Za-z_][A-Za-z0-9_]*)\s*\}\}")

_BUILDER_MODEL_PLACEHOLDER = "none (deterministic template compiler, no LLM -- see milestone 3b)"
_PROMPT_VERSION_PLACEHOLDER = "n/a (no LLM prompt; see milestone 3b)"


@dataclass(frozen=True, slots=True)
class SandboxResult:
    """Real results from an actual sandbox run (e.g. milestone 4a's), when one exists for this node."""

    passed: bool
    cases: int
    account: str | None


@dataclass(frozen=True, slots=True)
class PermissionResult:
    """The permission probe suite's latest result. Proxy-wide, not node-specific.

    Milestone 2d's probe suite tests the shared proxy's generic
    authorization behavior (redirect handling, secret injection, etc.),
    not anything about a particular compiled plan -- so this is the same
    fact for every node using this proxy, not something derived per node.
    """

    passed: bool
    attempted_violations: int


def _redact(value: str) -> str:
    return _SECRET_MARKER.sub(lambda match: f"<redacted:{match.group(1)}>", value)


def _capture_request(plan: dict[str, object], input_value: dict[str, object]) -> Request:
    """The exact Request the interpreter would send for `input_value`, with no network I/O.

    Reuses the real interpreter's own rendering path -- the same one the
    proxy independently re-derives against -- rather than reimplementing
    URL/header/query composition separately for this preview.
    """
    captured: list[Request] = []

    def transport(request: Request) -> Response:
        captured.append(request)
        return Response(status=200, headers={}, body={})

    run(plan, dict(input_value), transport=transport)
    return captured[0]


def _behaviour_summary(plan: Mapping[str, object]) -> str:
    steps = cast(list[Mapping[str, object]], plan["steps"])
    step = steps[0]
    expect = cast(Mapping[str, Mapping[str, object]], step["expect"])
    routes = sorted({cast(str, route["route"]) for route in expect.values()})
    return f"Sends one {step['method']} to {step['url']} and routes responses to {', '.join(routes)}."


def _request_preview(plan: dict[str, object], input_value: dict[str, object]) -> list[dict[str, object]]:
    steps = cast(list[Mapping[str, object]], plan["steps"])
    step_id = cast(str, steps[0]["id"])
    request = _capture_request(plan, input_value)
    return [{
        "step_id": step_id,
        "method": request.method,
        "url": request.url,
        "headers": {name: _redact(value) for name, value in request.headers.items()},
        "rendered_from": {"input": dict(input_value)},
    }]


def _capabilities(plan: Mapping[str, object]) -> dict[str, object]:
    steps = cast(list[Mapping[str, object]], plan["steps"])
    methods = sorted({cast(str, step["method"]) for step in steps})
    return {
        "hosts": list(cast(list[str], plan["hosts"])),
        "methods": methods,
        # Phase 3 never generates a plan that references {{ secret.X }} --
        # every compiled operation is a public or already-authless GET.
        "secrets": [],
        "egress_default": "deny",
    }


def _assumption(claim: Claim, source_document_id: str) -> dict[str, object]:
    label = "success response body shape" if "Success response body" in claim.claim else "generated-plan limitation"
    return {
        "claim": label,
        "basis": claim.claim,
        "source_document_id": source_document_id,
        "source_span": list(claim.source_span),
    }


def assemble_evidence(
    *,
    node_id: str,
    semver: str,
    status: str,
    artifact_hash: str,
    operation: Operation,
    result: CompileResult,
    sample_input: dict[str, object],
    claims: tuple[Claim, ...],
    source_document_id: str,
    source_hash: str,
    mock_result: MockTestResult | None = None,
    sandbox_result: SandboxResult | None = None,
    permission_result: PermissionResult | None = None,
) -> dict[str, object]:
    """Assemble the full evidence bundle for one compiled node version.

    `result.plan` must be set (i.e. `result.coverage != "not_representable"`)
    -- there is nothing to preview, mock-test, or make capability claims
    about for an operation that didn't compile.
    """
    if result.plan is None or result.input_schema is None or result.output_schema is None:
        raise ValueError("cannot assemble evidence for a not_representable compile result")

    mock = mock_result if mock_result is not None else run_mock_case(result.plan, golden_case(result.input_schema))
    sandbox = sandbox_result or SandboxResult(passed=False, cases=0, account=None)
    permission = permission_result or PermissionResult(passed=False, attempted_violations=0)

    return {
        "artifact_hash": artifact_hash,
        "status": status,
        "behaviour_summary": _behaviour_summary(result.plan),
        "request_preview": _request_preview(result.plan, sample_input),
        "input_schema": result.input_schema,
        "output_schema": result.output_schema,
        "capabilities": _capabilities(result.plan),
        "side_effect_profile": "read_only",
        "assumptions": [_assumption(claim, source_document_id) for claim in claims],
        "verification": {
            "static": {"passed": result.coverage != "not_representable", "checks": list(_STATIC_CHECKS)},
            "mock": {"passed": mock.passed, "cases": 1},
            "sandbox": {"passed": sandbox.passed, "cases": sandbox.cases, "account": sandbox.account},
            "permission": {"passed": permission.passed, "attempted_violations": permission.attempted_violations},
        },
        # No trace-storage system exists yet in this codebase (a real
        # GET /v1/traces/{id} backing store) -- present and honestly empty
        # rather than a fabricated trace_url pointing at nothing real.
        "traces": [],
        "provenance": {
            "source_documents": [source_hash],
            "compiler_version": COMPILER_VERSION,
            "builder_model": _BUILDER_MODEL_PLACEHOLDER,
            "prompt_version": _PROMPT_VERSION_PLACEHOLDER,
            "plan_coverage": result.coverage,
        },
    }
