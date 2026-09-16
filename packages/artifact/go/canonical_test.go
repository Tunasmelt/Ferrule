package artifact

import (
	"bytes"
	"os"
	"path/filepath"
	"sort"
	"testing"
)

func TestSharedFixturesAreCanonical(t *testing.T) {
	paths, err := filepath.Glob(filepath.Join("..", "..", "..", "tests", "fixtures", "canonical", "*.json"))
	if err != nil {
		t.Fatal(err)
	}
	sort.Strings(paths)
	if len(paths) != 20 {
		t.Fatalf("got %d fixtures, want 20", len(paths))
	}
	for _, path := range paths {
		raw, err := os.ReadFile(path)
		if err != nil {
			t.Fatal(err)
		}
		first, err := Canonicalize(raw)
		if err != nil {
			t.Fatalf("%s: %v", path, err)
		}
		second, err := Canonicalize(first)
		if err != nil {
			t.Fatalf("%s second pass: %v", path, err)
		}
		if !bytes.Equal(first, second) {
			t.Errorf("%s is not idempotent", path)
		}
	}
}

func TestRejectsNonFiniteNumbers(t *testing.T) {
	for _, input := range []string{`{"n":NaN}`, `{"n":Infinity}`, `{"n":-Infinity}`} {
		if _, err := Canonicalize([]byte(input)); err == nil {
			t.Errorf("Canonicalize(%q) succeeded", input)
		}
	}
}
