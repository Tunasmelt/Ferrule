import sys
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / "services" / "compiler" / "python"))

from ferrule_compiler.api import create_app  # noqa: E402


class CompilerAPITests(unittest.TestCase):
    def setUp(self) -> None:
        self.client = TestClient(create_app())
        self.fixture = ROOT / "tests" / "fixtures" / "openapi" / "jsonplaceholder.json"

    def register_and_extract(self) -> str:
        response = self.client.post(
            "/sources",
            json={"name": "JSONPlaceholder", "base_url": "https://jsonplaceholder.typicode.com", "auth_kind": "bearer"},
        )
        self.assertEqual(201, response.status_code)
        source_id = response.json()["id"]
        with self.fixture.open("rb") as document:
            uploaded = self.client.post(
                f"/sources/{source_id}/documents",
                data={"kind": "openapi"},
                files={"file": (self.fixture.name, document, "application/json")},
            )
        self.assertEqual(201, uploaded.status_code)
        extracted = self.client.post(f"/sources/{source_id}/extract")
        self.assertEqual(202, extracted.status_code)
        body = extracted.json()
        self.assertEqual("succeeded", body["status"])
        self.assertEqual(3, body["result"]["operations_found"])
        self.assertEqual(1.0, body["result"]["confidence"])
        self.assertEqual(0, body["result"]["claims"])
        polled = self.client.get(body["poll_url"])
        self.assertEqual(body, polled.json())
        return source_id

    def test_full_ingest_resolve_and_resume_flow(self) -> None:
        source_id = self.register_and_extract()
        operations = self.client.get(f"/sources/{source_id}/operations")
        self.assertEqual(200, operations.status_code)
        self.assertEqual({"getPost", "getPostComments", "getUser"}, {
            item["operation_id"] for item in operations.json()["data"]
        })

        resolved = self.client.post(
            f"/sources/{source_id}/resolve",
            json={"task": "Fetch a single post resource by its id"},
        )
        self.assertEqual(202, resolved.status_code)
        self.assertEqual("succeeded", resolved.json()["status"])
        self.assertEqual("getPost", resolved.json()["operation"]["operation_id"])
        self.assertEqual(resolved.json(), self.client.get(resolved.json()["poll_url"]).json())

        ambiguous = self.client.post(
            f"/sources/{source_id}/resolve",
            json={"task": "Fetch a single resource by its numeric id"},
        )
        self.assertEqual(202, ambiguous.status_code)
        body = ambiguous.json()
        self.assertEqual("needs_input", body["status"])
        self.assertTrue({"getPost", "getUser"}.issubset(
            {item["operation_id"] for item in body["options"]}
        ))

        resumed = self.client.post(body["resume_url"], json={"choice": "getUser"})
        self.assertEqual(200, resumed.status_code)
        self.assertEqual("succeeded", resumed.json()["status"])
        self.assertEqual("getUser", resumed.json()["operation"]["operation_id"])
        self.assertEqual(resumed.json(), self.client.get(resumed.json()["poll_url"]).json())

    def test_unknown_source_uses_error_envelope(self) -> None:
        response = self.client.get("/sources/missing/operations")
        self.assertEqual(404, response.status_code)
        self.assertEqual("source_not_found", response.json()["error"]["code"])
        self.assertTrue(response.json()["error"]["request_id"])

    def test_malformed_json_is_400_error_envelope(self) -> None:
        response = self.client.post(
            "/sources",
            content=b"{broken",
            headers={"content-type": "application/json"},
        )
        self.assertEqual(400, response.status_code)
        self.assertEqual("malformed_request", response.json()["error"]["code"])

    def test_oversized_document_upload_is_rejected(self) -> None:
        response = self.client.post(
            "/sources",
            json={"name": "Oversized", "base_url": "https://example.com", "auth_kind": "bearer"},
        )
        source_id = response.json()["id"]
        oversized = b"0" * (10 * 1024 * 1024 + 1)
        uploaded = self.client.post(
            f"/sources/{source_id}/documents",
            data={"kind": "openapi"},
            files={"file": ("huge.json", oversized, "application/json")},
        )
        self.assertEqual(413, uploaded.status_code)
        self.assertEqual("document_too_large", uploaded.json()["error"]["code"])

    def test_resuming_a_job_twice_is_rejected(self) -> None:
        source_id = self.register_and_extract()
        ambiguous = self.client.post(
            f"/sources/{source_id}/resolve",
            json={"task": "Fetch a single resource by its numeric id"},
        )
        resume_url = ambiguous.json()["resume_url"]
        first = self.client.post(resume_url, json={"choice": "getUser"})
        self.assertEqual(200, first.status_code)
        second = self.client.post(resume_url, json={"choice": "getPost"})
        self.assertEqual(409, second.status_code)
        self.assertEqual("job_not_resumable", second.json()["error"]["code"])


if __name__ == "__main__":
    unittest.main()
