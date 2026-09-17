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
            (
                fixture_dir / f"{number:02d}-{name}-old.json",
                fixture_dir / f"{number:02d}-{name}-new.json",
            )
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

    def schema_result(
        self, old_port: dict[str, object], new_port: dict[str, object]
    ) -> dict[str, object]:
        return diff(
            {"output_schema": {"ports": {"ok": old_port}}},
            {"output_schema": {"ports": {"ok": new_port}}},
        )

    def test_five_pairs_have_documented_shape_and_stable_output(self) -> None:
        for old, new in self.pairs:
            first = diff(old.read_bytes(), new.read_bytes())
            second = diff(old.read_bytes(), new.read_bytes())
            self.assertEqual(
                {
                    "schema_changes",
                    "plan_changes",
                    "capability_changes",
                    "breaking",
                    "breaking_reason",
                },
                set(first),
            )
            self.assertEqual(
                json.dumps(first, indent=2, sort_keys=True),
                json.dumps(second, indent=2, sort_keys=True),
            )

    def test_breaking_required_addition_and_optional_addition(self) -> None:
        required = self.result(0)
        self.assertEqual(
            [
                {
                    "port": "ok",
                    "field": "invoice.tax_total",
                    "change": "added",
                    "type": "number",
                }
            ],
            required["schema_changes"],
        )
        self.assertIs(required["breaking"], True)
        self.assertEqual(
            "output port 'ok' gained a required field", required["breaking_reason"]
        )

        optional = self.result(1)
        self.assertEqual(
            [{"port": "ok", "field": "note", "change": "added", "type": "string"}],
            optional["schema_changes"],
        )
        self.assertIs(optional["breaking"], False)
        self.assertIsNone(optional["breaking_reason"])

    def test_plan_capability_and_empty_changes(self) -> None:
        self.assertEqual(
            [
                {
                    "step": "fetch",
                    "field": "url",
                    "from": "/v2/invoices",
                    "to": "/v3/invoices",
                }
            ],
            self.result(2)["plan_changes"],
        )
        self.assertEqual(
            [
                {
                    "field": "hosts",
                    "from": ["api.acme.example"],
                    "to": ["api.acme.example", "uploads.acme.example"],
                }
            ],
            self.result(3)["capability_changes"],
        )
        self.assertEqual(
            {
                "schema_changes": [],
                "plan_changes": [],
                "capability_changes": [],
                "breaking": False,
                "breaking_reason": None,
            },
            self.result(4),
        )

    def test_plan_step_reorder_is_visible_but_not_breaking(self) -> None:
        old = {"plan": {"steps": [{"id": "a"}, {"id": "b"}]}}
        new = {"plan": {"steps": [{"id": "b"}, {"id": "a"}]}}

        result = diff(old, new)

        self.assertEqual(
            [{"field": "order", "from": ["a", "b"], "to": ["b", "a"]}],
            result["plan_changes"],
        )
        self.assertEqual([], result["schema_changes"])
        self.assertEqual([], result["capability_changes"])
        self.assertIs(result["breaking"], False)

    def test_plan_level_hosts_change_is_visible(self) -> None:
        old = {"plan": {"hosts": ["api.example"], "steps": [{"id": "a"}]}}
        new = {
            "plan": {
                "hosts": ["api.example", "uploads.example"],
                "steps": [{"id": "a"}],
            }
        }

        result = diff(old, new)

        self.assertEqual(
            [
                {
                    "field": "hosts",
                    "from": ["api.example"],
                    "to": ["api.example", "uploads.example"],
                }
            ],
            result["plan_changes"],
        )

    def test_bare_plan_document_hosts_change_is_visible(self) -> None:
        # Milestone 1a's actual plan document shape: "hosts" and "steps"
        # both live at the TOP level, with no "plan" wrapper key at all.
        # This is the shape the original audit finding reproduced against
        # (distinct from a full node manifest's nested plan.steps, and from
        # a hypothetical "hosts nested inside plan" shape that doesn't
        # actually occur anywhere in this codebase).
        old = {"hosts": ["api.example"], "steps": [{"id": "a"}]}
        new = {"hosts": ["api.example", "uploads.example"], "steps": [{"id": "a"}]}

        result = diff(old, new)

        self.assertEqual(
            [{"field": "hosts", "from": ["api.example"], "to": ["api.example", "uploads.example"]}],
            result["plan_changes"],
        )
        self.assertIs(result["breaking"], False)

    def test_duplicate_step_id_is_visible(self) -> None:
        old = {"plan": {"steps": [{"id": "a"}, {"id": "a"}]}}
        new = {"plan": {"steps": [{"id": "a"}]}}

        result = diff(old, new)

        self.assertEqual(
            [
                {
                    "step": "a",
                    "field": "id",
                    "change": "duplicate",
                    "from": 2,
                    "to": 1,
                }
            ],
            result["plan_changes"],
        )

    def test_existing_field_becoming_required_is_breaking(self) -> None:
        old: dict[str, object] = {
            "type": "object",
            "properties": {"status": {"type": "string"}},
        }
        new: dict[str, object] = {**old, "required": ["status"]}

        result = self.schema_result(old, new)

        self.assertEqual(
            [
                {
                    "port": "ok",
                    "field": "status",
                    "change": "became_required",
                    "from": False,
                    "to": True,
                }
            ],
            result["schema_changes"],
        )
        self.assertIs(result["breaking"], True)

    def test_new_or_narrowed_field_constraints_are_breaking(self) -> None:
        cases = {
            "enum": (["ready", "done"], ["ready"]),
            "const": (None, "ready"),
            "pattern": (None, "^[a-z]+$"),
            "minimum": (0, 1),
            "maximum": (10, 9),
            "exclusiveMinimum": (0, 1),
            "exclusiveMaximum": (10, 9),
            "additionalProperties": (True, False),
        }
        for constraint, (before, after) in cases.items():
            with self.subTest(constraint=constraint):
                old_field: dict[str, object] = {
                    "type": "object"
                    if constraint == "additionalProperties"
                    else "string"
                }
                new_field = dict(old_field)
                if before is not None:
                    old_field[constraint] = before
                new_field[constraint] = after

                result = self.schema_result(
                    {"type": "object", "properties": {"status": old_field}},
                    {"type": "object", "properties": {"status": new_field}},
                )

                self.assertEqual(
                    [
                        {
                            "port": "ok",
                            "field": "status",
                            "change": "constraint_changed",
                            "constraint": constraint,
                            "from": before,
                            "to": after,
                        }
                    ],
                    result["schema_changes"],
                )
                self.assertIs(result["breaking"], True)

    def test_empty_output_port_removal_is_breaking(self) -> None:
        result = diff(
            {"output_schema": {"ports": {"ok": {"type": "object"}}}},
            {"output_schema": {"ports": {}}},
        )

        self.assertEqual(
            [{"port": "ok", "field": "", "change": "port_removed"}],
            result["schema_changes"],
        )
        self.assertIs(result["breaking"], True)

    def test_enum_widening_is_visible_but_not_breaking(self) -> None:
        result = self.schema_result(
            {
                "type": "object",
                "properties": {"status": {"type": "string", "enum": ["ready"]}},
            },
            {
                "type": "object",
                "properties": {"status": {"type": "string", "enum": ["ready", "done"]}},
            },
        )

        self.assertEqual(
            [
                {
                    "port": "ok",
                    "field": "status",
                    "change": "constraint_changed",
                    "constraint": "enum",
                    "from": ["ready"],
                    "to": ["ready", "done"],
                }
            ],
            result["schema_changes"],
        )
        self.assertIs(result["breaking"], False)


if __name__ == "__main__":
    unittest.main()
