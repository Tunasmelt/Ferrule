import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).parents[1]
PACKAGE_ROOT = ROOT / "packages" / "plan-schema" / "python"
sys.path.insert(0, str(PACKAGE_ROOT))

from ferrule_plan_schema import check, validate_schema  # noqa: E402


class PlanSchemaTests(unittest.TestCase):
    def setUp(self) -> None:
        self.fixtures = ROOT / "tests" / "fixtures" / "plans"

    @staticmethod
    def load(path: Path) -> object:
        return json.loads(path.read_text(encoding="utf-8"))

    def test_valid_fixtures_have_no_findings(self) -> None:
        fixtures = sorted((self.fixtures / "valid").glob("*.json"))
        self.assertGreaterEqual(len(fixtures), 3)
        for fixture in fixtures:
            with self.subTest(fixture=fixture.name):
                plan = self.load(fixture)
                self.assertEqual([], validate_schema(plan))
                self.assertEqual([], check(plan))

    def test_invalid_fixtures_have_expected_finding(self) -> None:
        expected = {
            "missing-default.json": "MISSING_DEFAULT_ROUTE",
            "unbound-template.json": "UNBOUND_TEMPLATE_VARIABLE",
            "undeclared-host.json": "UNDECLARED_HOST",
            "unbounded-pagination.json": "UNBOUNDED_PAGINATION",
        }
        for name, code in expected.items():
            with self.subTest(fixture=name):
                findings = check(self.load(self.fixtures / "invalid" / name))
                self.assertIn(code, {finding.code for finding in findings})

    def test_schema_rejects_empty_mapping_expression(self) -> None:
        plan = self.load(self.fixtures / "valid" / "none.json")
        self.assertIsInstance(plan, dict)
        assert isinstance(plan, dict)
        steps = plan["steps"]
        assert isinstance(steps, list)
        step = steps[0]
        assert isinstance(step, dict)
        expect = step["expect"]
        assert isinstance(expect, dict)
        default = expect["default"]
        assert isinstance(default, dict)
        default["map"] = {"reason": ""}
        self.assertTrue(validate_schema(plan))
        self.assertIn("SCHEMA_INVALID", {finding.code for finding in check(plan)})

    def test_package_contains_no_execution_capability(self) -> None:
        forbidden = (
            "import requests",
            "from requests",
            "import httpx",
            "from httpx",
            "urllib.request",
            "import subprocess",
            "from subprocess",
            "os.system",
        )
        for path in PACKAGE_ROOT.rglob("*.py"):
            source = path.read_text(encoding="utf-8")
            for token in forbidden:
                with self.subTest(path=path.name, token=token):
                    self.assertNotIn(token, source)


if __name__ == "__main__":
    unittest.main()
