package artifact

import (
	"encoding/json"
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
