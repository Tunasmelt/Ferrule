package artifact

import (
	"bytes"
	"errors"
	"os"
	"path/filepath"
	"sort"
	"strings"
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

func TestRejectsDuplicateObjectKeys(t *testing.T) {
	for _, input := range []string{`{"x":1,"x":2}`, `{"a":{"x":1,"x":2}}`} {
		_, err := Canonicalize([]byte(input))
		if !errors.Is(err, ErrNonCanonical) || !strings.Contains(err.Error(), `duplicate object key: "x"`) {
			t.Errorf("Canonicalize(%q) error = %v", input, err)
		}
	}
}

func TestRejectsUnpairedSurrogateEscapes(t *testing.T) {
	// Matches Python's canonicalizer, which rejects these outright rather
	// than silently substituting U+FFFD the way encoding/json does by
	// default -- a lone surrogate escape must fail the same way in both
	// languages, not just happen to produce the same bytes when it doesn't.
	for _, input := range []string{`{"x":"\ud800"}`, `{"x":"\udc00"}`} {
		_, err := Canonicalize([]byte(input))
		if !errors.Is(err, ErrNonCanonical) {
			t.Errorf("Canonicalize(%q) error = %v, want ErrNonCanonical", input, err)
		}
	}
}

func TestAcceptsValidSurrogatePairEscape(t *testing.T) {
	out, err := Canonicalize([]byte(`{"x":"a😀b"}`))
	if err != nil {
		t.Fatalf("Canonicalize error = %v", err)
	}
	want := "{\"x\":\"a\U0001F600b\"}"
	if string(out) != want {
		t.Errorf("Canonicalize = %q, want %q", out, want)
	}
}
