import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / "services" / "compiler" / "python"))

from ferrule_compiler.generate import compile_operation  # noqa: E402
from ferrule_compiler.openapi import Operation, Parameter, ingest  # noqa: E402
from ferrule_plan_schema import check as check_plan  # noqa: E402

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


class CompilerGenerateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        fixtures_dir = ROOT / "tests" / "fixtures" / "openapi"
        cls.results = []
        for name, base_url in REAL_FIXTURES.items():
            spec = ingest((fixtures_dir / name).read_bytes())
            for operation in spec.operations:
                if operation.method == "GET":
                    cls.results.append((name, operation, compile_operation(base_url, operation)))

    def test_at_least_20_get_operations_are_covered(self) -> None:
        self.assertGreaterEqual(len(self.results), 20)

    def test_every_get_operation_is_representable_or_representable_partial(self) -> None:
        # 100% valid-plan-or-not_representable, never a silently wrong plan:
        # for these 8 real, hand-authored specs (all clean identifiers, all
        # path/query parameters), every GET operation should compile.
        for name, operation, result in self.results:
            with self.subTest(fixture=name, operation=operation.operation_id):
                self.assertIn(result.coverage, ("representable", "representable_partial"))
                self.assertIsNotNone(result.plan)

    def test_generated_plans_actually_pass_the_static_checker(self) -> None:
        # Proves generation cannot mark a plan representable without the
        # checker having actually run on it -- re-run it independently here
        # rather than trusting compile_operation's own internal call.
        for name, operation, result in self.results:
            with self.subTest(fixture=name, operation=operation.operation_id):
                assert result.plan is not None
                findings = check_plan(result.plan)
                self.assertEqual([], findings, f"{operation.operation_id} plan failed the static checker: {findings}")

    def test_optional_query_parameter_yields_representable_partial(self) -> None:
        # github's issues/list-for-repo has an optional "state" query param.
        match = next(
            (result for name, operation, result in self.results if operation.operation_id == "issues/list-for-repo"),
            None,
        )
        assert match is not None
        self.assertEqual("representable_partial", match.coverage)
        self.assertEqual(1, len(match.limitations))
        self.assertIn("state", match.limitations[0])

    def test_operation_with_no_optional_parameters_is_fully_representable(self) -> None:
        match = next(
            (result for name, operation, result in self.results if operation.operation_id == "getPost"),
            None,
        )
        assert match is not None
        self.assertEqual("representable", match.coverage)
        self.assertEqual((), match.limitations)

    def test_input_schema_marks_path_and_required_query_params_required(self) -> None:
        match = next(
            (result for name, operation, result in self.results if operation.operation_id == "repos/get"),
            None,
        )
        assert match is not None
        assert match.input_schema is not None
        self.assertEqual({"owner", "repo"}, set(match.input_schema["required"]))  # type: ignore[index]
        self.assertEqual({"owner", "repo"}, set(match.input_schema["properties"]))  # type: ignore[index]

    def test_cookie_parameter_is_not_representable_with_a_reason(self) -> None:
        fixtures_dir = ROOT / "tests" / "fixtures" / "openapi"
        spec = ingest((fixtures_dir / "synthetic-cookie-param.json").read_bytes())
        operation = spec.operations[0]
        result = compile_operation("https://example.invalid", operation)
        self.assertEqual("not_representable", result.coverage)
        self.assertIsNone(result.plan)
        self.assertTrue(result.reasons)
        self.assertIn("session_id", result.reasons[0])
        self.assertIn("cookie", result.reasons[0])

    def test_non_get_operation_is_not_representable(self) -> None:
        fixtures_dir = ROOT / "tests" / "fixtures" / "openapi"
        spec = ingest((fixtures_dir / "github.json").read_bytes())
        post_operation = next(item for item in spec.operations if item.operation_id == "issues/create")
        result = compile_operation("https://api.github.com", post_operation)
        self.assertEqual("not_representable", result.coverage)
        self.assertIsNone(result.plan)

    def test_unresolvable_host_is_not_representable(self) -> None:
        fixtures_dir = ROOT / "tests" / "fixtures" / "openapi"
        spec = ingest((fixtures_dir / "jsonplaceholder.json").read_bytes())
        operation = next(item for item in spec.operations if item.operation_id == "getPost")
        result = compile_operation("not-a-url", operation)
        self.assertEqual("not_representable", result.coverage)

    def test_undeclared_path_placeholder_is_not_representable(self) -> None:
        # A documentation error: "/widgets/{id}" has no declared "id" path
        # parameter. Silently leaving the literal "{id}" in the URL would
        # pass every static check while being wrong at request time.
        operation = Operation(
            operation_id="getWidget",
            method="GET",
            path="/widgets/{id}",
            summary="",
            description="",
            tags=(),
            parameters=(),
        )
        result = compile_operation("https://example.com", operation)
        self.assertEqual("not_representable", result.coverage)
        self.assertIn("id", result.reasons[0])

    def test_case_mismatched_path_parameter_is_not_representable(self) -> None:
        # The declared parameter name doesn't exactly match the path's
        # placeholder text -- same failure mode as the undeclared case.
        operation = Operation(
            operation_id="getWidget",
            method="GET",
            path="/widgets/{ID}",
            summary="",
            description="",
            tags=(),
            parameters=(Parameter(name="id", location="path", required=True, schema_type="string"),),
        )
        result = compile_operation("https://example.com", operation)
        self.assertEqual("not_representable", result.coverage)

    def test_cross_location_name_collision_is_not_representable(self) -> None:
        # A path parameter and a query parameter sharing the same name would
        # otherwise silently collapse onto one shared input.<name> variable.
        operation = Operation(
            operation_id="getWidget",
            method="GET",
            path="/widgets/{id}",
            summary="",
            description="",
            tags=(),
            parameters=(
                Parameter(name="id", location="path", required=True, schema_type="string"),
                Parameter(name="id", location="query", required=False, schema_type="string"),
            ),
        )
        result = compile_operation("https://example.com", operation)
        self.assertEqual("not_representable", result.coverage)
        self.assertIn("id", result.reasons[0])


if __name__ == "__main__":
    unittest.main()
