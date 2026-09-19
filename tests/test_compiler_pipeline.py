"""Whole-Phase-3 audit finding: no test previously drove ingest -> resolve ->
generate -> mock-verify -> claims through the real HTTP API end-to-end.
Every 3a test stayed at the HTTP/store layer; every 3b/3c test loaded
fixtures from disk directly and called internal functions, bypassing the
API layer entirely. This test proves the full pipeline actually composes,
using only what a real caller of the API could obtain.
"""

import sys
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / "services" / "compiler" / "python"))

from ferrule_compiler.api import create_app  # noqa: E402
from ferrule_compiler.claims import extract_claims  # noqa: E402
from ferrule_compiler.generate import compile_operation  # noqa: E402
from ferrule_compiler.mocktest import golden_case, run_mock_case  # noqa: E402
from ferrule_compiler.openapi import ingest, operation_from_mapping  # noqa: E402


class CompilerPipelineTests(unittest.TestCase):
    def setUp(self) -> None:
        self.client = TestClient(create_app())
        self.fixture = ROOT / "tests" / "fixtures" / "openapi" / "github.json"

    def test_full_pipeline_composes_through_the_real_api(self) -> None:
        source = self.client.post(
            "/sources",
            json={"name": "GitHub", "base_url": "https://api.github.com", "auth_kind": "bearer"},
        ).json()
        source_id = source["id"]

        with self.fixture.open("rb") as file:
            document = self.client.post(
                f"/sources/{source_id}/documents",
                data={"kind": "openapi"},
                files={"file": (self.fixture.name, file, "application/json")},
            ).json()

        self.client.post(f"/sources/{source_id}/extract")
        operations = self.client.get(f"/sources/{source_id}/operations").json()["data"]
        repos_get_json = next(op for op in operations if op["operation_id"] == "repos/get")

        # Everything downstream uses only data a real caller could retrieve
        # through the API -- not the original in-process Python objects.
        fetched_source = self.client.get(f"/sources/{source_id}").json()
        self.assertEqual("https://api.github.com", fetched_source["base_url"])

        raw_bytes = self.client.get(f"/sources/{source_id}/documents/{document['id']}").content
        self.assertEqual(self.fixture.read_bytes(), raw_bytes)

        operation = operation_from_mapping(repos_get_json)
        result = compile_operation(fetched_source["base_url"], operation)
        self.assertEqual("representable", result.coverage)
        assert result.plan is not None and result.input_schema is not None

        claims = extract_claims(raw_bytes, operation, result)
        self.assertGreaterEqual(len(claims), 1)

        outcome = run_mock_case(result.plan, golden_case(result.input_schema))
        self.assertTrue(outcome.passed, outcome.failure)

        # The API round-trip (JSON out, adapter back in) must be lossless:
        # compiling from it should produce the identical plan as compiling
        # directly from ingest(), never a silently different one.
        direct_operation = next(
            item for item in ingest(self.fixture.read_bytes()).operations if item.operation_id == "repos/get"
        )
        direct_result = compile_operation("https://api.github.com", direct_operation)
        self.assertEqual(direct_result.plan, result.plan)

    def test_document_from_a_different_source_is_not_retrievable(self) -> None:
        source_a = self.client.post(
            "/sources", json={"name": "A", "base_url": "https://a.example.com", "auth_kind": "bearer"}
        ).json()
        source_b = self.client.post(
            "/sources", json={"name": "B", "base_url": "https://b.example.com", "auth_kind": "bearer"}
        ).json()
        with self.fixture.open("rb") as file:
            document = self.client.post(
                f"/sources/{source_a['id']}/documents",
                data={"kind": "openapi"},
                files={"file": (self.fixture.name, file, "application/json")},
            ).json()

        cross_source = self.client.get(f"/sources/{source_b['id']}/documents/{document['id']}")
        self.assertEqual(404, cross_source.status_code)


if __name__ == "__main__":
    unittest.main()
