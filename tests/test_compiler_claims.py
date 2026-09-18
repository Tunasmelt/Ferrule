import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / "services" / "compiler" / "python"))

from ferrule_compiler.claims import extract_claims  # noqa: E402
from ferrule_compiler.generate import compile_operation  # noqa: E402
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


class CompilerClaimsTests(unittest.TestCase):
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
                    cls.compiled.append((name, operation, result))

    def test_every_compiled_get_operation_carries_at_least_one_claim(self) -> None:
        for name, operation, result in self.compiled:
            with self.subTest(fixture=name, operation=operation.operation_id):
                claims = extract_claims(self.raw_by_fixture[name], operation, result)
                self.assertGreaterEqual(len(claims), 1)

    def test_ambiguous_operation_carries_multiple_claims_with_resolvable_spans(self) -> None:
        # github's issues/list-for-repo is known-ambiguous on two counts: an
        # undocumented response body shape (true of every operation here)
        # AND an optional query parameter ("state") the plan language can't
        # conditionally omit -- exactly the kind of spec ambiguity this
        # deliverable exists to surface.
        raw = self.raw_by_fixture["github.json"]
        operation, result = next(
            (operation, result)
            for name, operation, result in self.compiled
            if operation.operation_id == "issues/list-for-repo"
        )
        claims = extract_claims(raw, operation, result)
        self.assertGreaterEqual(len(claims), 2)

        state_claim = next(claim for claim in claims if "state" in claim.claim)
        start, end = state_claim.source_span
        self.assertGreater(end, start, "span must be non-empty to be resolvable")
        resolved_text = raw.decode("utf-8")[start:end]
        # A resolvable span: the exact bytes it points to are the real
        # parameter-name declaration text from the source document, not a
        # fabricated or off-by-N offset.
        self.assertEqual('"state"', resolved_text)

    def test_response_shape_claim_span_resolves_to_the_correct_operation_block(self) -> None:
        raw = self.raw_by_fixture["jsonplaceholder.json"]
        operation, result = next(
            (operation, result)
            for name, operation, result in self.compiled
            if operation.operation_id == "getUser"
        )
        claims = extract_claims(raw, operation, result)
        response_claim = next(claim for claim in claims if "Success response body" in claim.claim)
        start, end = response_claim.source_span
        resolved_text = raw.decode("utf-8")[start:end]
        # The span should cover getUser's own operation block, not getPost's
        # or getPostComments' (all three share this fixture).
        self.assertIn('"getUser"', resolved_text)
        self.assertNotIn('"getPostComments"', resolved_text)

    def test_operation_with_no_optional_parameters_has_exactly_one_claim(self) -> None:
        raw = self.raw_by_fixture["jsonplaceholder.json"]
        operation, result = next(
            (operation, result)
            for name, operation, result in self.compiled
            if operation.operation_id == "getPost"
        )
        claims = extract_claims(raw, operation, result)
        self.assertEqual(1, len(claims))
        self.assertIn("Success response body", claims[0].claim)

    def test_uncompiled_operation_carries_no_claims(self) -> None:
        raw = self.raw_by_fixture["github.json"]
        spec = ingest(raw)
        post_operation = next(item for item in spec.operations if item.operation_id == "issues/create")
        post_result = compile_operation("https://api.github.com", post_operation)
        self.assertEqual((), extract_claims(raw, post_operation, post_result))


if __name__ == "__main__":
    unittest.main()
