import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / "services" / "compiler" / "python"))

from ferrule_compiler.openapi import (  # noqa: E402
    InvalidDocumentError,
    InvalidOpenAPIError,
    ingest,
)


class CompilerIngestTests(unittest.TestCase):
    def setUp(self) -> None:
        self.fixtures = ROOT / "tests" / "fixtures" / "openapi"

    def test_all_openapi_fixtures_ingest(self) -> None:
        names = {
            "github.json",
            "stripe.json",
            "pokeapi.json",
            "jsonplaceholder.json",
            "open-meteo.json",
            "slack.json",
            "sendgrid.json",
            "twilio.json",
        }
        for name in names:
            with self.subTest(name=name):
                result = ingest((self.fixtures / name).read_bytes())
                self.assertRegex(result.source_hash, r"^sha256:[0-9a-f]{64}$")
                self.assertTrue(result.openapi_version.startswith("3."))
                self.assertGreater(len(result.operations), 0)
                for operation in result.operations:
                    self.assertIn(operation.method, {"GET", "POST", "PUT", "PATCH", "DELETE"})
                    self.assertTrue(operation.operation_id)
                    self.assertTrue(operation.path.startswith("/"))

    def test_known_operations_are_extracted(self) -> None:
        github = ingest((self.fixtures / "github.json").read_bytes())
        self.assertIn(
            ("issues/create", "POST", "/repos/{owner}/{repo}/issues"),
            {(item.operation_id, item.method, item.path) for item in github.operations},
        )
        twilio = ingest((self.fixtures / "twilio.json").read_bytes())
        self.assertIn(
            ("CreateMessage", "POST", "/2010-04-01/Accounts/{AccountSid}/Messages.json"),
            {(item.operation_id, item.method, item.path) for item in twilio.operations},
        )

    def test_invalid_serialization_has_specific_error(self) -> None:
        with self.assertRaises(InvalidDocumentError):
            ingest(b"[not: valid: yaml")

    def test_missing_openapi_structure_has_specific_error(self) -> None:
        with self.assertRaises(InvalidOpenAPIError):
            ingest(b'{"hello": "world"}')

    def test_yaml_document_is_accepted(self) -> None:
        result = ingest(b"""openapi: 3.0.0
info: {title: Example, version: '1'}
paths:
  /widgets:
    get:
      operationId: listWidgets
      responses: {'200': {description: OK}}
""")
        self.assertEqual("listWidgets", result.operations[0].operation_id)

    def test_missing_operation_id_gets_stable_fallback(self) -> None:
        raw = b'{"openapi":"3.0.0","info":{},"paths":{"/widgets/{id}":{"get":{"responses":{}}}}}'
        first = ingest(raw).operations[0]
        second = ingest(raw).operations[0]
        self.assertEqual("get-widgets-by-id", first.operation_id)
        self.assertEqual(first.operation_id, second.operation_id)

    def test_colliding_fallback_ids_are_disambiguated(self) -> None:
        # "/foo/bar" and "/foo-bar" both tokenize to the same words, so their
        # synthesized fallback ids would collide without disambiguation --
        # an undetected collision lets a resume's exact-id lookup silently
        # resolve to the wrong operation.
        raw = (
            b'{"openapi":"3.0.0","info":{},"paths":{'
            b'"/foo/bar":{"get":{"responses":{}}},'
            b'"/foo-bar":{"get":{"responses":{}}}'
            b"}}"
        )
        operations = ingest(raw).operations
        ids = [item.operation_id for item in operations]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertIn("get-foo-bar", ids)
        self.assertIn("get-foo-bar-2", ids)


if __name__ == "__main__":
    unittest.main()
