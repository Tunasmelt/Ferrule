import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / "services" / "compiler" / "python"))

from ferrule_compiler.openapi import ingest  # noqa: E402
from ferrule_compiler.resolve import ResolutionStatus, resolve_operation  # noqa: E402


class CompilerResolveTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        fixture = ROOT / "tests" / "fixtures" / "openapi" / "jsonplaceholder.json"
        cls.operations = ingest(fixture.read_bytes()).operations

    def test_exact_description_resolves_get_post(self) -> None:
        result = resolve_operation("Fetch a single post resource by its id", self.operations)
        self.assertEqual(ResolutionStatus.RESOLVED, result.status)
        self.assertIsNotNone(result.operation)
        self.assertEqual("getPost", result.operation.operation_id)

    def test_parallel_descriptions_are_ambiguous(self) -> None:
        result = resolve_operation("Fetch a single resource by its numeric id", self.operations)
        self.assertEqual(ResolutionStatus.AMBIGUOUS, result.status)
        self.assertTrue({"getPost", "getUser"}.issubset(
            {operation.operation_id for operation in result.candidates}
        ))
        self.assertNotIn("getPostComments", {item.operation_id for item in result.candidates})

    def test_irrelevant_task_has_no_match(self) -> None:
        result = resolve_operation("launch a satellite into orbit", self.operations)
        self.assertEqual(ResolutionStatus.NO_MATCH, result.status)
        self.assertIsNone(result.operation)
        self.assertEqual((), result.candidates)


if __name__ == "__main__":
    unittest.main()
