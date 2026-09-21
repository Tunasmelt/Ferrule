import base64
import sys
import unittest
from dataclasses import FrozenInstanceError
from pathlib import Path

from fastapi.testclient import TestClient

ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / "services" / "compiler" / "python"))
sys.path.insert(0, str(ROOT / "packages" / "artifact" / "python"))

from ferrule_artifact import build as build_artifact  # noqa: E402
from ferrule_artifact import verify as artifact_verify  # noqa: E402
from ferrule_compiler.api import create_app  # noqa: E402
from ferrule_compiler.openapi import Operation  # noqa: E402
from ferrule_compiler.store import NodeVersion, NodeVersionUpdateError, Store  # noqa: E402


class CompilerApprovalAPITests(unittest.TestCase):
    def setUp(self) -> None:
        self.client = TestClient(create_app())
        self.fixture = ROOT / "tests" / "fixtures" / "openapi" / "github.json"

    def _compile_repos_get(self) -> dict[str, object]:
        source_id = self.client.post(
            "/sources", json={"name": "gh", "base_url": "https://api.github.com", "auth_kind": "bearer"}
        ).json()["id"]
        with self.fixture.open("rb") as file:
            self.client.post(
                f"/sources/{source_id}/documents",
                data={"kind": "openapi"},
                files={"file": (self.fixture.name, file, "application/json")},
            )
        self.client.post(f"/sources/{source_id}/extract")
        return self.client.post(
            "/nodes/compile",
            json={"source_id": source_id, "task": "Get a repository given its owner and repo"},
        ).json()

    def test_approval_produces_a_genuinely_verifiable_signed_artifact(self) -> None:
        compiled = self._compile_repos_get()
        approve_url = compiled["evidence_url"].replace("/evidence", "/approve")

        response = self.client.post(approve_url, json={"reviewer_note": "checked against docs"})
        self.assertEqual(200, response.status_code)
        body = response.json()
        self.assertEqual("approved", body["status"])
        self.assertEqual(compiled["artifact_hash"], body["artifact_hash"])
        self.assertEqual("checked against docs", body["reviewer_note"])

        signature = base64.b64decode(body["signature"])
        self.assertTrue(
            artifact_verify(build_artifact(body["plan"]), signature, body["public_key_pem"].encode("ascii"))
        )

        # Not a rubber-stamp check: a tampered plan must fail verification
        # against the same signature/key.
        tampered = dict(body["plan"])
        tampered["hosts"] = ["evil.example.com"]
        self.assertFalse(
            artifact_verify(build_artifact(tampered), signature, body["public_key_pem"].encode("ascii"))
        )

    def test_second_approval_attempt_is_rejected_with_409(self) -> None:
        compiled = self._compile_repos_get()
        approve_url = compiled["evidence_url"].replace("/evidence", "/approve")

        first = self.client.post(approve_url, json={"reviewer_note": "ok"})
        self.assertEqual(200, first.status_code)

        second = self.client.post(approve_url, json={"reviewer_note": "ok again"})
        self.assertEqual(409, second.status_code)
        self.assertEqual("already_approved", second.json()["error"]["code"])

    def test_approving_unknown_node_version_is_404(self) -> None:
        response = self.client.post(
            "/nodes/nd_missing/versions/1.0.0/approve", json={"reviewer_note": "n/a"}
        )
        self.assertEqual(404, response.status_code)
        self.assertEqual("node_version_not_found", response.json()["error"]["code"])

    def test_node_version_detail_reflects_approval_without_changing_other_fields(self) -> None:
        compiled = self._compile_repos_get()
        detail_url = compiled["evidence_url"].replace("/evidence", "")
        approve_url = compiled["evidence_url"].replace("/evidence", "/approve")

        before = self.client.get(detail_url).json()
        self.assertEqual("proposed", before["status"])
        self.assertIsNone(before["signature"])

        self.client.post(approve_url, json={"reviewer_note": "ok"})
        after = self.client.get(detail_url).json()
        self.assertEqual("approved", after["status"])
        self.assertIsNotNone(after["signature"])
        # Everything except status/signature/public_key_pem/approved_at/
        # reviewer_note must be byte-identical to before approval.
        self.assertEqual(before["plan"], after["plan"])
        self.assertEqual(before["artifact_hash"], after["artifact_hash"])
        self.assertEqual(before["node_version_id"], after["node_version_id"])


class NodeVersionImmutabilityStoreTests(unittest.TestCase):
    """Invariant 4, checked at the store/"ORM" layer directly, not just the API surface."""

    def _sample_node_version(self, **overrides: object) -> NodeVersion:
        operation = Operation(
            operation_id="getWidget", method="GET", path="/widgets/{id}",
            summary="", description="", tags=(), parameters=(),
        )
        defaults: dict[str, object] = dict(
            id="nv_1", node_id="nd_1", semver="1.0.0", status="proposed",
            artifact_hash="sha256:" + "0" * 64, source_id="src_1", source_document_id="doc_1",
            operation=operation, plan={"hosts": ["example.com"], "steps": []},
            input_schema={"type": "object", "properties": {}, "required": []},
            output_schema={"ports": {}}, coverage="representable", limitations=(),
        )
        defaults.update(overrides)
        return NodeVersion(**defaults)  # type: ignore[arg-type]

    def test_node_version_dataclass_is_frozen(self) -> None:
        node_version = self._sample_node_version()
        with self.assertRaises(FrozenInstanceError):
            node_version.plan = {"hosts": ["evil.example.com"], "steps": []}  # type: ignore[misc]

    def test_approve_node_version_only_changes_approval_fields(self) -> None:
        store = Store()
        store.put_node_version(self._sample_node_version())
        approved = store.approve_node_version("nd_1", "1.0.0", "sig", "key", "2026-01-01T00:00:00Z", "note")
        original = self._sample_node_version()
        self.assertEqual(original.plan, approved.plan)
        self.assertEqual(original.input_schema, approved.input_schema)
        self.assertEqual(original.output_schema, approved.output_schema)
        self.assertEqual(original.operation, approved.operation)
        self.assertEqual(original.coverage, approved.coverage)
        self.assertEqual(original.artifact_hash, approved.artifact_hash)
        self.assertEqual("approved", approved.status)
        self.assertEqual("sig", approved.signature)

    def test_approving_twice_at_the_store_layer_is_rejected(self) -> None:
        store = Store()
        store.put_node_version(self._sample_node_version())
        store.approve_node_version("nd_1", "1.0.0", "sig", "key", "2026-01-01T00:00:00Z", "note")
        with self.assertRaises(NodeVersionUpdateError) as context:
            store.approve_node_version("nd_1", "1.0.0", "sig2", "key2", "2026-01-02T00:00:00Z", "note2")
        self.assertEqual("already_approved", context.exception.reason)

    def test_put_node_version_refuses_to_overwrite_an_approved_entry(self) -> None:
        # Today's only caller (_compile_and_store) always mints a fresh
        # node_id, so this path is unreachable via the current API -- this
        # proves the store layer itself refuses it regardless, per
        # invariant 4's "no code path" wording, not just the ones wired up
        # today.
        store = Store()
        store.put_node_version(self._sample_node_version())
        store.approve_node_version("nd_1", "1.0.0", "sig", "key", "2026-01-01T00:00:00Z", "note")
        different_plan = self._sample_node_version(plan={"hosts": ["evil.example.com"], "steps": []})
        with self.assertRaises(NodeVersionUpdateError) as context:
            store.put_node_version(different_plan)
        self.assertEqual("immutable", context.exception.reason)
        # And the stored version is provably unchanged by the attempt.
        stored = store.get_node_version("nd_1", "1.0.0")
        assert stored is not None
        self.assertEqual({"hosts": ["example.com"], "steps": []}, stored.plan)


if __name__ == "__main__":
    unittest.main()
