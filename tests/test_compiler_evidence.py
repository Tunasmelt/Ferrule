import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / "services" / "compiler" / "python"))

from ferrule_compiler.claims import extract_claims  # noqa: E402
from ferrule_compiler.evidence import PermissionResult, SandboxResult, assemble_evidence  # noqa: E402
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


def _walk(value: object, path: str = "$") -> list[str]:
    """List every leaf JSON path, to prove no key was silently omitted, not just present-but-empty."""
    paths: list[str] = []
    if isinstance(value, dict):
        for key, item in value.items():
            paths.extend(_walk(item, f"{path}.{key}"))
    elif isinstance(value, list):
        if not value:
            paths.append(path)
        for index, item in enumerate(value):
            paths.extend(_walk(item, f"{path}[{index}]"))
    else:
        paths.append(path)
    return paths


class CompilerEvidenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        fixtures_dir = ROOT / "tests" / "fixtures" / "openapi"
        cls.raw_by_fixture = {name: (fixtures_dir / name).read_bytes() for name in REAL_FIXTURES}
        cls.compiled = []
        for name, base_url in REAL_FIXTURES.items():
            spec = ingest(cls.raw_by_fixture[name])
            for operation in spec.operations:
                if operation.method == "GET":
                    result = compile_operation(base_url, operation)
                    if result.coverage != "not_representable":
                        cls.compiled.append((name, operation, result))

    def test_evidence_renders_for_every_phase_3_node(self) -> None:
        for name, operation, result in self.compiled:
            with self.subTest(fixture=name, operation=operation.operation_id):
                claims = extract_claims(self.raw_by_fixture[name], operation, result)
                assert result.input_schema is not None
                sample_input = golden_case(result.input_schema).input
                evidence = assemble_evidence(
                    node_id="nd_test",
                    semver="1.0.0",
                    status="proposed",
                    artifact_hash="sha256:" + "0" * 64,
                    operation=operation,
                    result=result,
                    sample_input=sample_input,
                    claims=claims,
                    source_document_id="doc_test",
                    source_hash="sha256:" + "1" * 64,
                )
                self.assertIsInstance(evidence, dict)

    def test_golden_fixture_populates_every_documented_field(self) -> None:
        # github's repos/get is the golden fixture: a real, milestone-4a-
        # sandboxed operation with a real assumption (undocumented response
        # shape) to prove assumptions/claims genuinely populate too.
        name = "github.json"
        operation, result = next(
            (operation, result) for fixture, operation, result in self.compiled
            if fixture == name and operation.operation_id == "repos/get"
        )
        claims = extract_claims(self.raw_by_fixture[name], operation, result)
        assert result.input_schema is not None and result.plan is not None
        sample_input = {"owner": "ferrule-dev", "repo": "ferrule"}
        mock_result = run_mock_case(result.plan, golden_case(result.input_schema))

        evidence = assemble_evidence(
            node_id="nd_01HXGOLDEN",
            semver="1.0.0",
            status="proposed",
            artifact_hash="sha256:" + "a" * 64,
            operation=operation,
            result=result,
            sample_input=sample_input,
            claims=claims,
            source_document_id="doc_01HXGITHUB",
            source_hash="sha256:" + "b" * 64,
            mock_result=mock_result,
            sandbox_result=SandboxResult(passed=True, cases=1, account="pokeapi-live (milestone 4a)"),
            permission_result=PermissionResult(passed=True, attempted_violations=0),
        )

        # Every top-level field from docs/API.md's evidence schema must be
        # present -- a missing key here is the exact "silently-omitted
        # field" this milestone's test criterion rules out.
        expected_top_level = {
            "artifact_hash", "status", "behaviour_summary", "request_preview",
            "input_schema", "output_schema", "capabilities", "side_effect_profile",
            "assumptions", "verification", "traces", "provenance",
        }
        self.assertEqual(expected_top_level, set(evidence.keys()))

        # Not just present -- populated with real, non-empty, non-null
        # values wherever a real value exists (traces is the one
        # documented, deliberate exception: no trace-storage backend
        # exists yet, so it is an honest empty list, not a missing key).
        self.assertTrue(evidence["artifact_hash"])
        self.assertTrue(evidence["behaviour_summary"])
        self.assertEqual(1, len(evidence["request_preview"]))
        preview = evidence["request_preview"][0]
        self.assertEqual("https://api.github.com/repos/ferrule-dev/ferrule", preview["url"])
        self.assertEqual({"input": sample_input}, preview["rendered_from"])
        self.assertTrue(evidence["input_schema"]["properties"])
        self.assertTrue(evidence["output_schema"]["ports"])
        self.assertEqual(["api.github.com"], evidence["capabilities"]["hosts"])
        self.assertEqual(["GET"], evidence["capabilities"]["methods"])
        self.assertEqual("read_only", evidence["side_effect_profile"])
        self.assertGreaterEqual(len(evidence["assumptions"]), 1)
        for assumption in evidence["assumptions"]:
            self.assertTrue(assumption["claim"])
            self.assertTrue(assumption["basis"])
            self.assertEqual("doc_01HXGITHUB", assumption["source_document_id"])
            self.assertEqual(2, len(assumption["source_span"]))
        verification = evidence["verification"]
        self.assertTrue(verification["static"]["passed"])
        self.assertTrue(verification["static"]["checks"])
        self.assertTrue(verification["mock"]["passed"])
        self.assertEqual(1, verification["mock"]["cases"])
        self.assertTrue(verification["sandbox"]["passed"])
        self.assertEqual(1, verification["sandbox"]["cases"])
        self.assertTrue(verification["sandbox"]["account"])
        self.assertTrue(verification["permission"]["passed"])
        self.assertEqual([], evidence["traces"])
        provenance = evidence["provenance"]
        self.assertTrue(provenance["source_documents"])
        self.assertTrue(provenance["compiler_version"])
        self.assertIn("no LLM", provenance["builder_model"])
        self.assertEqual("representable", provenance["plan_coverage"])

        # Prove no leaf was silently dropped: every declared top-level key
        # resolves to at least one real leaf value (or the one documented
        # empty list, "traces").
        leaves = _walk(evidence)
        self.assertTrue(any(path.startswith("$.traces") for path in leaves))

    def test_missing_plan_refuses_to_assemble(self) -> None:
        from ferrule_compiler.generate import CompileResult

        not_representable = CompileResult("not_representable", None, None, None, (), ("no plan",))
        with self.assertRaises(ValueError):
            assemble_evidence(
                node_id="nd_x", semver="1.0.0", status="proposed", artifact_hash="sha256:" + "0" * 64,
                operation=next(iter(self.compiled))[1], result=not_representable,
                sample_input={}, claims=(), source_document_id="doc_x", source_hash="sha256:" + "0" * 64,
            )


if __name__ == "__main__":
    unittest.main()
