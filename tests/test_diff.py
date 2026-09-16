import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / "packages" / "artifact" / "python"))

from ferrule_artifact import diff  # noqa: E402


class DiffTests(unittest.TestCase):
    def setUp(self) -> None:
        fixture_dir = ROOT / "tests" / "fixtures" / "diff"
        self.pairs = [
            (fixture_dir / f"{number:02d}-{name}-old.json", fixture_dir / f"{number:02d}-{name}-new.json")
            for number, name in (
                (1, "required-addition"),
                (2, "optional-unmapped"),
                (3, "plan-url"),
                (4, "capability"),
                (5, "no-change"),
            )
        ]

    def result(self, index: int) -> dict[str, object]:
        old, new = self.pairs[index]
        return diff(json.loads(old.read_text()), json.loads(new.read_text()))

    def test_five_pairs_have_documented_shape_and_stable_output(self) -> None:
        for old, new in self.pairs:
            first = diff(old.read_bytes(), new.read_bytes())
            second = diff(old.read_bytes(), new.read_bytes())
            self.assertEqual(
                {"schema_changes", "plan_changes", "capability_changes", "breaking", "breaking_reason"},
                set(first),
            )
            self.assertEqual(
                json.dumps(first, indent=2, sort_keys=True),
                json.dumps(second, indent=2, sort_keys=True),
            )

    def test_breaking_required_addition_and_optional_addition(self) -> None:
        required = self.result(0)
        self.assertEqual(
            [{"port": "ok", "field": "invoice.tax_total", "change": "added", "type": "number"}],
            required["schema_changes"],
        )
        self.assertIs(required["breaking"], True)
        self.assertEqual("output port 'ok' gained a required field", required["breaking_reason"])

        optional = self.result(1)
        self.assertEqual(
            [{"port": "ok", "field": "note", "change": "added", "type": "string"}],
            optional["schema_changes"],
        )
        self.assertIs(optional["breaking"], False)
        self.assertIsNone(optional["breaking_reason"])

    def test_plan_capability_and_empty_changes(self) -> None:
        self.assertEqual(
            [{"step": "fetch", "field": "url", "from": "/v2/invoices", "to": "/v3/invoices"}],
            self.result(2)["plan_changes"],
        )
        self.assertEqual(
            [{"field": "hosts", "from": ["api.acme.example"], "to": ["api.acme.example", "uploads.acme.example"]}],
            self.result(3)["capability_changes"],
        )
        self.assertEqual(
            {"schema_changes": [], "plan_changes": [], "capability_changes": [], "breaking": False, "breaking_reason": None},
            self.result(4),
        )


if __name__ == "__main__":
    unittest.main()
