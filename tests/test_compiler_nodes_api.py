import sys
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / "services" / "compiler" / "python"))

from ferrule_compiler.api import create_app  # noqa: E402

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


class CompilerNodesAPITests(unittest.TestCase):
    def setUp(self) -> None:
        self.client = TestClient(create_app())

    def _register_source(self, name: str, base_url: str) -> str:
        fixture = ROOT / "tests" / "fixtures" / "openapi" / name
        source_id = self.client.post(
            "/sources", json={"name": name, "base_url": base_url, "auth_kind": "bearer"}
        ).json()["id"]
        with fixture.open("rb") as file:
            self.client.post(
                f"/sources/{source_id}/documents",
                data={"kind": "openapi"},
                files={"file": (fixture.name, file, "application/json")},
            )
        self.client.post(f"/sources/{source_id}/extract")
        return source_id

    def test_compile_resolves_and_evidence_renders(self) -> None:
        source_id = self._register_source("github.json", "https://api.github.com")
        compiled = self.client.post(
            "/nodes/compile",
            json={"source_id": source_id, "task": "Get a repository given its owner and repo"},
        )
        self.assertEqual(202, compiled.status_code)
        body = compiled.json()
        self.assertEqual("proposed", body["status"])
        self.assertEqual("representable", body["plan_coverage"])
        self.assertTrue(body["artifact_hash"].startswith("sha256:"))

        evidence = self.client.get(body["evidence_url"])
        self.assertEqual(200, evidence.status_code)
        evidence_body = evidence.json()
        self.assertEqual(body["artifact_hash"], evidence_body["artifact_hash"])
        self.assertEqual("proposed", evidence_body["status"])
        self.assertTrue(evidence_body["behaviour_summary"])
        self.assertGreaterEqual(len(evidence_body["assumptions"]), 1)
        self.assertTrue(evidence_body["verification"]["mock"]["passed"])

    def test_compile_ambiguous_task_then_resume_finishes_compiling(self) -> None:
        source_id = self._register_source("jsonplaceholder.json", "https://jsonplaceholder.typicode.com")
        compiled = self.client.post(
            "/nodes/compile",
            json={"source_id": source_id, "task": "Fetch a single resource by its numeric id"},
        )
        self.assertEqual(202, compiled.status_code)
        body = compiled.json()
        self.assertEqual("needs_input", body["status"])
        self.assertGreaterEqual(len(body["options"]), 2)

        resumed = self.client.post(body["resume_url"], json={"choice": "getUser"})
        self.assertEqual(200, resumed.status_code)
        resumed_body = resumed.json()
        self.assertEqual("proposed", resumed_body["status"])
        self.assertEqual("representable", resumed_body["plan_coverage"])

        evidence = self.client.get(resumed_body["evidence_url"])
        self.assertEqual(200, evidence.status_code)
        self.assertIn("id", evidence.json()["input_schema"]["properties"])

        # Polling the job after resume must reflect the finished compile,
        # not fall through to a stale needs_input response.
        job_id = body["resume_url"].split("/")[2]
        polled = self.client.get(f"/jobs/{job_id}")
        self.assertEqual(200, polled.status_code)
        self.assertEqual("proposed", polled.json()["status"])

    def test_compile_non_get_operation_returns_not_representable_failure(self) -> None:
        source_id = self._register_source("github.json", "https://api.github.com")
        compiled = self.client.post(
            "/nodes/compile",
            json={"source_id": source_id, "task": "Create an issue in a repository"},
        )
        self.assertEqual(202, compiled.status_code)
        body = compiled.json()
        self.assertEqual("failed", body["status"])
        self.assertEqual("not_representable", body["plan_coverage"])
        self.assertTrue(body["reasons"])

    def test_evidence_for_unknown_node_is_404(self) -> None:
        response = self.client.get("/nodes/nd_missing/versions/1.0.0/evidence")
        self.assertEqual(404, response.status_code)
        self.assertEqual("node_version_not_found", response.json()["error"]["code"])

    def test_evidence_renders_for_every_real_get_operation_through_the_api(self) -> None:
        for name, base_url in REAL_FIXTURES.items():
            source_id = self._register_source(name, base_url)
            operations = self.client.get(f"/sources/{source_id}/operations").json()["data"]
            for operation in operations:
                if operation["method"] != "GET":
                    continue
                with self.subTest(fixture=name, operation=operation["operation_id"]):
                    # Use the operation's own full text as its task: this
                    # test proves compile+evidence wiring end-to-end for
                    # every real operation, not resolve.py's fuzzy-match
                    # quality (already covered by test_compiler_resolve.py)
                    # -- an operation's own text against itself always
                    # scores as at least as good a match as any candidate,
                    # so resolution succeeding here is guaranteed by
                    # construction, not a coincidence of task phrasing.
                    task = " ".join(
                        filter(None, [operation["summary"], operation["description"], operation["operation_id"]])
                    )
                    compiled = self.client.post(
                        "/nodes/compile", json={"source_id": source_id, "task": task}
                    ).json()
                    self.assertNotEqual(
                        "needs_input", compiled.get("status"),
                        f"{operation['operation_id']}'s own text should resolve to itself unambiguously",
                    )
                    self.assertNotEqual(
                        "failed", compiled.get("status"),
                        f"{operation['operation_id']} should compile: {compiled.get('reasons')}",
                    )
                    evidence = self.client.get(compiled["evidence_url"])
                    self.assertEqual(200, evidence.status_code)

    def test_resume_compile_failure_returns_clean_error_and_does_not_get_stuck(self) -> None:
        # Whole-milestone audit finding: resume_needs_input already commits
        # a kind="compile" job as "succeeded" (atomically, single-use)
        # before the actual compile step runs. Without handling, any
        # exception during that step -- confirmed via require_source/
        # require_spec or an unexpected compile_operation failure -- left
        # the job permanently stuck (already consumed, unresumable) and
        # crashed both the immediate resume call and any later poll with a
        # raw, unhandled 500 instead of a clean error envelope.
        from unittest.mock import patch

        import ferrule_compiler.api as api_module

        source_id = self._register_source("jsonplaceholder.json", "https://jsonplaceholder.typicode.com")
        compiled = self.client.post(
            "/nodes/compile",
            json={"source_id": source_id, "task": "Fetch a single resource by its numeric id"},
        ).json()
        resume_url = compiled["resume_url"]
        job_id = resume_url.split("/")[2]

        with patch.object(api_module, "compile_operation", side_effect=RuntimeError("boom")):
            resumed = self.client.post(resume_url, json={"choice": "getUser"})
        self.assertEqual(500, resumed.status_code)
        self.assertEqual("compile_failed", resumed.json()["error"]["code"])

        polled = self.client.get(f"/jobs/{job_id}")
        self.assertEqual(500, polled.status_code)
        self.assertEqual("compile_failed", polled.json()["error"]["code"])

        resumed_again = self.client.post(resume_url, json={"choice": "getUser"})
        self.assertEqual(409, resumed_again.status_code)
        self.assertEqual("job_not_resumable", resumed_again.json()["error"]["code"])


if __name__ == "__main__":
    unittest.main()
