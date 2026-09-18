"""Mock test generation and execution for compiled plans (milestone 3c).

Reuses 1c's real interpreter (`ferrule_interpreter.run`) and its
`check(plan)` hard gate unchanged -- this module only supplies a canned,
in-process transport (no sockets, no fixture files) and synthesizes input
values from a compiled operation's input_schema, then asserts the
interpreter selected the expected route and mapped the expected fields.
It does not re-test the interpreter's real HTTP layer, which 1c's own
15-plan fixture suite already covers; it tests that *this compiler's own
generated plans* route and map correctly, which is a property only the
compiler's output can prove.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, cast

from ferrule_interpreter import Response, run
from ferrule_interpreter.interpreter import Request

_PLACEHOLDER_BY_TYPE: dict[str, object] = {
    "string": "sample",
    "integer": 1,
    "number": 1.5,
    "boolean": True,
    "array": [],
    "object": {},
}


@dataclass(frozen=True, slots=True)
class MockCase:
    input: dict[str, object]
    mock_status: int
    mock_body: dict[str, object]


@dataclass(frozen=True, slots=True)
class MockTestResult:
    passed: bool
    route: str
    output: dict[str, object]
    failure: str | None = None


def synthesize_input(input_schema: Mapping[str, object]) -> dict[str, object]:
    """Deterministic placeholder values for every declared property, keyed by JSON Schema type.

    Supplies every property (not just required ones) so the primary mock
    case exercises a fully-populated request; the known empty-string-when-
    omitted behavior for optional parameters is already recorded as a plan
    limitation (generate.py) rather than re-tested here.
    """
    properties = cast(Mapping[str, Mapping[str, object]], input_schema.get("properties", {}))
    return {name: _PLACEHOLDER_BY_TYPE.get(cast(str, schema.get("type")), "sample") for name, schema in properties.items()}


def golden_case(input_schema: Mapping[str, object]) -> MockCase:
    """The one canonical happy-path mock case a compiled GET plan should satisfy."""
    return MockCase(
        input=synthesize_input(input_schema),
        mock_status=200,
        mock_body={"id": "sample-id", "name": "sample-name"},
    )


def run_mock_case(plan: dict[str, object], case: MockCase) -> MockTestResult:
    """Execute `plan` against a canned response, verifying route selection and output mapping.

    No network I/O: the transport is a plain Python closure returning the
    case's canned status/body regardless of the request it receives.
    """
    def transport(_request: Request) -> Response:
        return Response(status=case.mock_status, headers={}, body=case.mock_body)

    try:
        result = run(plan, dict(case.input), transport=transport)
    except Exception as error:  # noqa: BLE001 -- any interpreter failure is a mock-test failure, not a crash
        return MockTestResult(False, "", {}, f"{type(error).__name__}: {error}")

    route = cast(str, result["route"])
    output = cast(dict[str, object], result["output"])
    expected_route = "ok" if 200 <= case.mock_status < 300 else "error"
    if route != expected_route:
        return MockTestResult(False, route, output, f"expected route {expected_route!r}, got {route!r}")

    if expected_route == "ok":
        body = output.get("body")
        if not isinstance(body, Mapping) or not all(body.get(key) == value for key, value in case.mock_body.items()):
            return MockTestResult(False, route, output, f"'body' output {body!r} does not contain the mock response {case.mock_body!r}")
    else:
        if output.get("status") != case.mock_status:
            return MockTestResult(False, route, output, f"'status' output {output.get('status')!r} != mock status {case.mock_status!r}")

    return MockTestResult(True, route, output, None)
