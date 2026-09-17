package artifact

import (
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"reflect"
	"testing"
)

func diffFixture(t *testing.T, name string) ([]byte, []byte) {
	t.Helper()
	root := filepath.Join("..", "..", "..", "tests", "fixtures", "diff")
	oldManifest, err := os.ReadFile(filepath.Join(root, name+"-old.json"))
	if err != nil {
		t.Fatal(err)
	}
	newManifest, err := os.ReadFile(filepath.Join(root, name+"-new.json"))
	if err != nil {
		t.Fatal(err)
	}
	return oldManifest, newManifest
}

func TestDiffFiveFixturesIsDeterministic(t *testing.T) {
	for _, name := range []string{"01-required-addition", "02-optional-unmapped", "03-plan-url", "04-capability", "05-no-change"} {
		oldManifest, newManifest := diffFixture(t, name)
		first, err := Diff(oldManifest, newManifest)
		if err != nil {
			t.Fatal(err)
		}
		second, err := Diff(oldManifest, newManifest)
		if err != nil {
			t.Fatal(err)
		}
		firstJSON, _ := json.MarshalIndent(first, "", "  ")
		secondJSON, _ := json.MarshalIndent(second, "", "  ")
		if !reflect.DeepEqual(firstJSON, secondJSON) {
			t.Fatalf("%s diff was not deterministic", name)
		}
	}
}

func TestDiffClassifiesRequiredAndOptionalAdditions(t *testing.T) {
	oldManifest, newManifest := diffFixture(t, "01-required-addition")
	required, err := Diff(oldManifest, newManifest)
	if err != nil {
		t.Fatal(err)
	}
	if !required.Breaking || required.BreakingReason == nil || *required.BreakingReason != "output port 'ok' gained a required field" {
		t.Fatalf("unexpected required addition result: %#v", required)
	}
	oldManifest, newManifest = diffFixture(t, "02-optional-unmapped")
	optional, err := Diff(oldManifest, newManifest)
	if err != nil {
		t.Fatal(err)
	}
	if optional.Breaking || optional.BreakingReason != nil {
		t.Fatalf("unexpected optional addition result: %#v", optional)
	}
}

func TestDiffPlanStepReorderIsVisibleButNotBreaking(t *testing.T) {
	result, err := Diff(
		map[string]any{"plan": map[string]any{"steps": []any{map[string]any{"id": "a"}, map[string]any{"id": "b"}}}},
		map[string]any{"plan": map[string]any{"steps": []any{map[string]any{"id": "b"}, map[string]any{"id": "a"}}}},
	)
	if err != nil {
		t.Fatal(err)
	}
	want := []ValueChange{{Field: "order", From: []string{"a", "b"}, To: []string{"b", "a"}}}
	if !reflect.DeepEqual(result.PlanChanges, want) || len(result.SchemaChanges) != 0 || len(result.CapabilityChanges) != 0 || result.Breaking {
		t.Fatalf("unexpected reorder result: %#v", result)
	}
}

func TestDiffPlanHostsChangeIsVisible(t *testing.T) {
	result, err := Diff(
		map[string]any{"plan": map[string]any{"hosts": []any{"api.example"}, "steps": []any{map[string]any{"id": "a"}}}},
		map[string]any{"plan": map[string]any{"hosts": []any{"api.example", "uploads.example"}, "steps": []any{map[string]any{"id": "a"}}}},
	)
	if err != nil {
		t.Fatal(err)
	}
	want := []ValueChange{{Field: "hosts", From: []any{"api.example"}, To: []any{"api.example", "uploads.example"}}}
	if !reflect.DeepEqual(result.PlanChanges, want) {
		t.Fatalf("unexpected hosts result: %#v", result)
	}
}

func TestDiffBarePlanDocumentHostsChangeIsVisible(t *testing.T) {
	// Milestone 1a's actual plan document shape: "hosts" and "steps" both
	// live at the TOP level, with no "plan" wrapper key at all -- distinct
	// from a full node manifest's nested plan.steps, and from a
	// hypothetical "hosts nested inside plan" shape that doesn't actually
	// occur anywhere in this codebase.
	result, err := Diff(
		map[string]any{"hosts": []any{"api.example"}, "steps": []any{map[string]any{"id": "a"}}},
		map[string]any{"hosts": []any{"api.example", "uploads.example"}, "steps": []any{map[string]any{"id": "a"}}},
	)
	if err != nil {
		t.Fatal(err)
	}
	want := []ValueChange{{Field: "hosts", From: []any{"api.example"}, To: []any{"api.example", "uploads.example"}}}
	if !reflect.DeepEqual(result.PlanChanges, want) || result.Breaking {
		t.Fatalf("unexpected bare-plan hosts result: %#v", result)
	}
}

func TestDiffDuplicateStepIDIsVisible(t *testing.T) {
	result, err := Diff(
		map[string]any{"plan": map[string]any{"steps": []any{map[string]any{"id": "a"}, map[string]any{"id": "a"}}}},
		map[string]any{"plan": map[string]any{"steps": []any{map[string]any{"id": "a"}}}},
	)
	if err != nil {
		t.Fatal(err)
	}
	want := []ValueChange{{Step: "a", Field: "id", Change: "duplicate", From: 2, To: 1}}
	if !reflect.DeepEqual(result.PlanChanges, want) {
		t.Fatalf("unexpected duplicate result: %#v", result)
	}
}

func schemaResult(t *testing.T, oldPort, newPort map[string]any) DiffResult {
	t.Helper()
	result, err := Diff(
		map[string]any{"output_schema": map[string]any{"ports": map[string]any{"ok": oldPort}}},
		map[string]any{"output_schema": map[string]any{"ports": map[string]any{"ok": newPort}}},
	)
	if err != nil {
		t.Fatal(err)
	}
	return result
}

func TestDiffExistingFieldBecomingRequiredIsBreaking(t *testing.T) {
	oldPort := map[string]any{"type": "object", "properties": map[string]any{"status": map[string]any{"type": "string"}}}
	newPort := map[string]any{"type": "object", "properties": oldPort["properties"], "required": []any{"status"}}

	result := schemaResult(t, oldPort, newPort)

	want := []SchemaChange{{Port: "ok", Field: "status", Change: "became_required", From: false, To: true}}
	if !reflect.DeepEqual(result.SchemaChanges, want) || !result.Breaking {
		t.Fatalf("unexpected requiredness result: %#v", result)
	}
}

func TestDiffNewOrNarrowedConstraintsAreBreaking(t *testing.T) {
	cases := []struct {
		name      string
		before    any
		after     any
		fieldType string
		hasBefore bool
	}{
		{"enum", []any{"ready", "done"}, []any{"ready"}, "string", true},
		{"const", nil, "ready", "string", false},
		{"pattern", nil, "^[a-z]+$", "string", false},
		{"minimum", 0, 1, "number", true},
		{"maximum", 10, 9, "number", true},
		{"exclusiveMinimum", 0, 1, "number", true},
		{"exclusiveMaximum", 10, 9, "number", true},
		{"additionalProperties", true, false, "object", true},
	}
	for _, test := range cases {
		t.Run(test.name, func(t *testing.T) {
			oldField := map[string]any{"type": test.fieldType}
			if test.hasBefore {
				oldField[test.name] = test.before
			}
			newField := map[string]any{"type": test.fieldType, test.name: test.after}
			result := schemaResult(t,
				map[string]any{"type": "object", "properties": map[string]any{"status": oldField}},
				map[string]any{"type": "object", "properties": map[string]any{"status": newField}},
			)
			before, after := test.before, test.after
			if _, ok := before.(int); ok {
				before = json.Number(fmt.Sprint(before))
				after = json.Number(fmt.Sprint(after))
			}
			want := []SchemaChange{{Port: "ok", Field: "status", Change: "constraint_changed", Constraint: test.name, From: before, To: after}}
			if !reflect.DeepEqual(result.SchemaChanges, want) || !result.Breaking {
				t.Fatalf("unexpected constraint result: %#v", result)
			}
		})
	}
}

func TestDiffEmptyPortRemovalIsBreaking(t *testing.T) {
	result, err := Diff(
		map[string]any{"output_schema": map[string]any{"ports": map[string]any{"ok": map[string]any{"type": "object"}}}},
		map[string]any{"output_schema": map[string]any{"ports": map[string]any{}}},
	)
	if err != nil {
		t.Fatal(err)
	}
	want := []SchemaChange{{Port: "ok", Field: "", Change: "port_removed"}}
	if !reflect.DeepEqual(result.SchemaChanges, want) || !result.Breaking {
		t.Fatalf("unexpected port removal result: %#v", result)
	}
}

func TestDiffEnumWideningIsVisibleButNotBreaking(t *testing.T) {
	result := schemaResult(t,
		map[string]any{"type": "object", "properties": map[string]any{"status": map[string]any{"type": "string", "enum": []any{"ready"}}}},
		map[string]any{"type": "object", "properties": map[string]any{"status": map[string]any{"type": "string", "enum": []any{"ready", "done"}}}},
	)
	if len(result.SchemaChanges) != 1 || result.SchemaChanges[0].Change != "constraint_changed" || result.Breaking {
		t.Fatalf("unexpected enum widening result: %#v", result)
	}
}
