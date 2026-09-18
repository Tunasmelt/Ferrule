"""Deterministic GET-operation plan generation (milestone 3b).

SPEC.md section 8 describes generation via a "Builder model" (an LLM call
with a regenerate-on-failure loop driven by the static checker's findings).
This milestone's own test criteria -- 20+ real GET operations across 3a's
fixtures compiling to plans that pass the phase-1 static checker -- are
fully satisfiable without one: mapping a GET operation's path/query/header
parameters into the phase-1 plan language is mechanical, not judgment-
requiring. Real generation intelligence, and the provider/cost decision
that comes with it, is deferred to whichever later milestone first needs it
for cases this can't handle (request bodies, ambiguous response shapes).

Because generation here is deterministic, the "regenerate-on-failure loop"
degenerates to a single attempt: the same operation always produces the
same plan, so a static-check failure means the mapping is unrepresentable,
not a fixable mistake worth retrying. The loop's shape (generate, check,
classify) is still exactly what a future Builder-model generator would
plug into -- only the retry-with-feedback step is inert here by construction.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import urlsplit

from ferrule_interpreter.coverage import Coverage, classify_plan
from ferrule_plan_schema import check as check_plan

from .openapi import Operation, Parameter

# Must match the plan checker's template-reference grammar
# (packages/plan-schema/python/ferrule_plan_schema/checker.py's _REFERENCE)
# and the CEL identifier grammar -- a parameter name outside this can't be
# expressed as an "{{ input.<name> }}" template reference at all.
_IDENTIFIER = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_JSON_SCHEMA_TYPES = frozenset({"string", "integer", "number", "boolean", "array", "object"})
_SUPPORTED_LOCATIONS = frozenset({"path", "query", "header"})

_OUTPUT_SCHEMA: dict[str, object] = {
    "ports": {
        "ok": {"type": "object"},
        "error": {"type": "object"},
    }
}


@dataclass(frozen=True, slots=True)
class CompileResult:
    coverage: Coverage
    plan: dict[str, object] | None
    input_schema: dict[str, object] | None
    output_schema: dict[str, object] | None
    limitations: tuple[str, ...]
    reasons: tuple[str, ...] = ()


def _json_type(schema_type: str) -> str:
    return schema_type if schema_type in _JSON_SCHEMA_TYPES else "string"


def _input_schema(parameters: tuple[Parameter, ...]) -> dict[str, object]:
    properties = {parameter.name: {"type": _json_type(parameter.schema_type)} for parameter in parameters}
    required = sorted(parameter.name for parameter in parameters if parameter.required)
    return {"type": "object", "properties": properties, "required": required}


def _not_representable(*reasons: str) -> CompileResult:
    return CompileResult("not_representable", None, None, None, (), tuple(reasons))


def compile_operation(base_url: str, operation: Operation) -> CompileResult:
    """Deterministically map one GET operation onto a phase-1 plan.

    Never returns a plan that hasn't itself passed the phase-1 static
    checker (packages/plan-schema's `check`) -- a compile either yields a
    plan proven representable/representable_partial, or an explicit
    not_representable verdict with reasons. There is no code path that
    marks a plan representable without having run the checker on it.
    """
    if operation.method != "GET":
        return _not_representable("non-GET operations are out of scope for milestone 3b")

    for parameter in operation.parameters:
        if parameter.location not in _SUPPORTED_LOCATIONS:
            return _not_representable(
                f"parameter {parameter.name!r} uses unsupported location {parameter.location!r}"
            )
        if not _IDENTIFIER.fullmatch(parameter.name):
            return _not_representable(
                f"parameter name {parameter.name!r} is not a valid plan template identifier"
            )

    hostname = urlsplit(base_url).hostname
    if not hostname:
        return _not_representable(f"source base_url {base_url!r} has no resolvable hostname")

    path = operation.path
    for parameter in operation.parameters:
        if parameter.location == "path":
            path = path.replace("{" + parameter.name + "}", "{{ input." + parameter.name + " }}")

    query = {parameter.name: f"{{{{ input.{parameter.name} }}}}" for parameter in operation.parameters if parameter.location == "query"}
    headers = {parameter.name: f"{{{{ input.{parameter.name} }}}}" for parameter in operation.parameters if parameter.location == "header"}

    # Optional (non-required) query/header parameters render as an empty
    # string when the caller omits them (render.py's _lookup), rather than
    # being left out of the request entirely -- the plan language has no
    # conditional-inclusion primitive for that. Static checks can't see
    # this gap, so it's recorded as a named transformation limitation
    # rather than silently ignored, per SPEC.md's representable_partial
    # definition ("fits except for N named transformations").
    limitations = tuple(
        f"optional {parameter.location} parameter {parameter.name!r} is always sent "
        "(empty string when unset), never omitted"
        for parameter in operation.parameters
        if parameter.location in ("query", "header") and not parameter.required
    )

    plan: dict[str, object] = {
        "hosts": [hostname],
        "steps": [
            {
                "id": operation.operation_id,
                "method": "GET",
                "url": base_url.rstrip("/") + path,
                "headers": headers,
                **({"query": query} if query else {}),
                "pagination": "none",
                "expect": {
                    "200": {"route": "ok", "map": {"body": "response"}},
                    "default": {"route": "error", "map": {"status": "response.status"}},
                },
            }
        ],
    }

    findings = check_plan(plan)
    if findings:
        return _not_representable(*(f"{item.code} at {item.path}: {item.message}" for item in findings))

    coverage: Coverage = classify_plan(plan, limitations)
    return CompileResult(coverage, plan, _input_schema(operation.parameters), dict(_OUTPUT_SCHEMA), limitations)
