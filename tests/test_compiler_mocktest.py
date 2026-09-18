import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / "services" / "compiler" / "python"))

from ferrule_compiler.generate import compile_operation  # noqa: E402
from ferrule_compiler.mocktest import golden_case, run_mock_case  # noqa: E402
from ferrule_compiler.openapi import ingest  # noqa: E402

REAL_FIXTURES = {
    "github.json": "https://api.github.com",
    "stripe.json": "https://api.stripe.com",
    "pokeapi.json": "https://pokeapi.co/api/v2",
    "jsonplaceholder.json": "https://jsonplaceholder.typicode.com",
    "open-meteo.json": "https://api.open-meteo.com",
    "slack.json": "https://slack.com/api",
    "sendgrid.json": "https://api.sendgrid.com",
    "twilio.json": "https://api.twilio.com",
}


class CompilerMockTestTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        fixtures_dir = ROOT / "tests" / "fixtures" / "openapi"
        cls.compiled = []
        for name, base_url in REAL_FIXTURES.items():
            spec = ingest((fixtures_dir / name).read_bytes())
            for operation in spec.operations:
                if operation.method == "GET":
                    result = compile_operation(base_url, operation)
                    assert result.plan is not None
                    cls.compiled.append((operation, result))

    def test_at_least_80_percent_pass_mock_execution_on_first_attempt(self) -> None:
        outcomes = []
        for operation, result in self.compiled:
            assert result.plan is not None and result.input_schema is not None
            case = golden_case(result.input_schema)
            outcome = run_mock_case(result.plan, case)
            outcomes.append((operation.operation_id, outcome))

        passed = sum(1 for _, outcome in outcomes if outcome.passed)
        total = len(outcomes)
        rate = passed / total
        failures = [(op_id, outcome.failure) for op_id, outcome in outcomes if not outcome.passed]
        self.assertGreaterEqual(
            rate, 0.8, f"only {passed}/{total} ({rate:.0%}) passed mock execution; failures: {failures}"
        )
        # Record the real number, not just the pass/fail threshold.
        print(f"\nmock execution: {passed}/{total} ({rate:.0%}) passed on first attempt")

    def test_path_and_query_parameters_render_into_the_actual_request(self) -> None:
        match = next(
            (result for operation, result in self.compiled if operation.operation_id == "repos/get"),
            None,
        )
        assert match is not None and match.plan is not None and match.input_schema is not None
        case = golden_case(match.input_schema)
        outcome = run_mock_case(match.plan, case)
        self.assertTrue(outcome.passed, outcome.failure)
        self.assertEqual("ok", outcome.route)
        body = outcome.output["body"]
        assert isinstance(body, dict)
        self.assertEqual("sample-id", body["id"])
        self.assertEqual("sample-name", body["name"])

    def test_error_status_routes_to_error_with_status_captured(self) -> None:
        from ferrule_compiler.mocktest import MockCase

        match = next(
            (result for operation, result in self.compiled if operation.operation_id == "getPost"),
            None,
        )
        assert match is not None and match.plan is not None and match.input_schema is not None
        case = MockCase(input={"id": 1}, mock_status=404, mock_body={"error": "not found"})
        outcome = run_mock_case(match.plan, case)
        self.assertTrue(outcome.passed, outcome.failure)
        self.assertEqual("error", outcome.route)
        self.assertEqual(404, outcome.output["status"])


if __name__ == "__main__":
    unittest.main()
