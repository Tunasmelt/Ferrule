import sys
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).parents[1]
PACKAGE_ROOT = ROOT / "packages" / "plan-schema" / "python"
sys.path.insert(0, str(PACKAGE_ROOT))

from ferrule_plan_schema.cel import (  # noqa: E402
    CELCompileError,
    CELEvaluationError,
    compile_expression,
    evaluate,
    registered_functions,
)


class CELTests(unittest.TestCase):
    def test_evaluates_against_input_and_response(self) -> None:
        expression = compile_expression(
            "input.enabled && response.status == 200"
        )
        self.assertTrue(
            evaluate(
                expression,
                input={"enabled": True},
                response={"status": 200},
            )
        )

    def test_compile_rejects_secret_namespace_per_invariant_one(self) -> None:
        with self.assertRaisesRegex(CELCompileError, "secret"):
            compile_expression("secret.token")

    def test_compile_rejects_other_undeclared_names(self) -> None:
        with self.assertRaisesRegex(CELCompileError, "made_up"):
            compile_expression("made_up.value")

    def test_comprehension_local_is_scoped(self) -> None:
        compile_expression("input.items.map(item, item.name)")
        with self.assertRaisesRegex(CELCompileError, "item"):
            compile_expression("input.items.map(item, item.name) == item")

    def test_expensive_expression_is_terminated(self) -> None:
        expression = compile_expression(
            "input.values.exists(x, input.values.exists(y, x + y == -1))"
        )
        started = time.monotonic()
        with self.assertRaisesRegex(CELEvaluationError, "cost limit"):
            evaluate(
                expression,
                input={"values": list(range(10_000))},
                response={},
            )
        self.assertLess(time.monotonic() - started, 3.0)

    def test_only_standard_library_functions_are_registered(self) -> None:
        standard = {
            "!_", "-_", "_!=_", "_%_", "_&&_", "_*_", "_+_", "_-_",
            "_/_", "_<=_", "_<_", "_==_", "_>=_", "_>_", "_?_:_",
            "_[_]", "_in_", "_||_", "bool", "bytes", "contains", "double",
            "duration", "endsWith", "getDate", "getDayOfMonth", "getDayOfWeek",
            "getDayOfYear", "getFullYear", "getHours", "getMilliseconds",
            "getMinutes", "getMonth", "getSeconds", "int", "list", "map",
            "matches", "null_type", "size", "startsWith", "string", "timestamp",
            "type", "uint",
        }
        self.assertLessEqual(registered_functions(), standard)

    def test_package_uses_no_other_evaluator(self) -> None:
        forbidden = ("eval(", "exec(", "jinja2")
        package = PACKAGE_ROOT / "ferrule_plan_schema"
        for path in package.rglob("*.py"):
            source = path.read_text(encoding="utf-8").lower()
            for token in forbidden:
                with self.subTest(path=path.name, token=token):
                    self.assertNotIn(token, source)
        cel_source = (package / "cel.py").read_text(encoding="utf-8")
        self.assertIn("celpy", cel_source)


if __name__ == "__main__":
    unittest.main()
