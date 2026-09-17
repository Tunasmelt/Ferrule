package proxy

import (
	"bytes"
	"crypto/ed25519"
	"crypto/rand"
	"encoding/json"
	"go/scanner"
	"go/token"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"unicode"

	artifact "ferrule/packages/artifact/go"
)

func signedManifest(t *testing.T, manifest string) (string, []byte, ed25519.PublicKey) {
	t.Helper()
	publicKey, privateKey, err := ed25519.GenerateKey(rand.Reader)
	if err != nil {
		t.Fatal(err)
	}
	built, err := artifact.Build([]byte(manifest))
	if err != nil {
		t.Fatal(err)
	}
	signature, err := artifact.Sign(built, privateKey)
	if err != nil {
		t.Fatal(err)
	}
	return artifact.Hash(built), append(append([]byte(nil), built...), signature...), publicKey
}

func TestArtifactCacheVerifiesBeforeCaching(t *testing.T) {
	hash, signed, publicKey := signedManifest(t, `{"plan":{"steps":[]}}`)
	cache := NewArtifactCache()

	tampered := append([]byte(nil), signed...)
	tampered[0] ^= 1
	if err := cache.Push(hash, tampered, publicKey); err == nil {
		t.Fatal("tampered artifact accepted")
	}
	if _, ok := cache.Get(hash); ok {
		t.Fatal("tampered artifact was cached")
	}
	if err := cache.Push(hash, signed, publicKey); err != nil {
		t.Fatal(err)
	}
	manifest, ok := cache.Get(hash)
	if !ok || manifest["plan"] == nil {
		t.Fatal("verified artifact not retrievable")
	}
}

func TestRenderRequestFixtures(t *testing.T) {
	tests := []struct {
		name     string
		step     map[string]any
		input    map[string]any
		response map[string]any
		want     string
	}{
		{"basic", map[string]any{"method": "GET", "url": "https://x.test/{{ input.id }}", "headers": map[string]any{}}, map[string]any{"id": "42"}, nil, `{"method":"GET","url":"https://x.test/42","headers":{},"body":null}`},
		{"missing", map[string]any{"method": "GET", "url": "https://x.test/{{ input.missing }}", "headers": map[string]any{}}, nil, nil, `{"method":"GET","url":"https://x.test/","headers":{},"body":null}`},
		{"boolean", map[string]any{"method": "GET", "url": "https://x.test", "query": map[string]any{"enabled": "{{ input.ok }}"}, "headers": map[string]any{}}, map[string]any{"ok": true}, nil, `{"method":"GET","url":"https://x.test?enabled=true","headers":{},"body":null}`},
		{"secret", map[string]any{"method": "GET", "url": "https://x.test", "headers": map[string]any{"authorization": "Bearer {{ secret.TOKEN }}"}}, nil, nil, `{"method":"GET","url":"https://x.test","headers":{"Authorization":"Bearer {{ secret.TOKEN }}"},"body":null}`},
		{"query merge sort", map[string]any{"method": "GET", "url": "https://x.test/p?z=last&a=old", "query": map[string]any{"a": "new", "m": "a b"}, "headers": map[string]any{}}, nil, nil, `{"method":"GET","url":"https://x.test/p?a=new&m=a+b&z=last","headers":{},"body":null}`},
		{"headers", map[string]any{"method": "POST", "url": "https://x.test", "headers": map[string]any{"x-API-key": "v", "accept": "json"}}, nil, nil, `{"method":"POST","url":"https://x.test","headers":{"Accept":"json","X-Api-Key":"v"},"body":null}`},
		{"unicode body", map[string]any{"method": "POST", "url": "https://x.test", "headers": map[string]any{}, "body": map[string]any{"message": "héllo {{ input.face }}"}}, map[string]any{"face": "😀"}, nil, `{"method":"POST","url":"https://x.test","headers":{"Content-Type":"application/json"},"body":{"message":"h\u00e9llo \ud83d\ude00"}}`},
		{"special body", map[string]any{"method": "POST", "url": "https://x.test", "headers": map[string]any{}, "body": map[string]any{"z": "line\n\"quote\"\\slash", "a": "<tag>&"}}, nil, nil, `{"method":"POST","url":"https://x.test","headers":{"Content-Type":"application/json"},"body":{"a":"<tag>&","z":"line\n\"quote\"\\slash"}}`},
		{"body header casing", map[string]any{"method": "POST", "url": "https://x.test", "headers": map[string]any{"content-type": "text/plain"}, "body": map[string]any{}}, nil, nil, `{"method":"POST","url":"https://x.test","headers":{"Content-Type":"application/json"},"body":{}}`},
		{"response", map[string]any{"method": "GET", "url": "https://x.test/{{ response.item.id }}", "headers": map[string]any{}}, nil, map[string]any{"item": map[string]any{"id": "abc"}}, `{"method":"GET","url":"https://x.test/abc","headers":{},"body":null}`},
		{"unicode URL", map[string]any{"method": "GET", "url": "https://x.test/{{ input.name }}?x=1&x=2", "headers": map[string]any{}}, map[string]any{"name": "café"}, nil, `{"method":"GET","url":"https://x.test/caf\u00e9?x=2","headers":{},"body":null}`},
	}
	for _, test := range tests {
		t.Run(test.name, func(t *testing.T) {
			got, err := RenderRequest(test.step, test.input, test.response)
			if err != nil {
				t.Fatal(err)
			}
			if string(got) != test.want {
				t.Fatalf("got  %s\nwant %s", got, test.want)
			}
		})
	}
}

func TestRenderRequestDeterministic1000Times(t *testing.T) {
	step := map[string]any{"method": "POST", "url": "https://x.test/p?z=9", "query": map[string]any{"b": "{{ input.b }}", "a": "1"}, "headers": map[string]any{"x-z": "z", "a": "a"}, "body": map[string]any{"z": "{{ input.b }}", "a": "é"}}
	input := map[string]any{"b": "two words"}
	first, err := RenderRequest(step, input, nil)
	if err != nil {
		t.Fatal(err)
	}
	for i := 0; i < 1000; i++ {
		got, err := RenderRequest(step, input, nil)
		if err != nil {
			t.Fatal(err)
		}
		if !bytes.Equal(got, first) {
			t.Fatalf("render %d differs: %s != %s", i, got, first)
		}
	}
}

func setupAuthorization(t *testing.T) (*ArtifactCache, *MemoryRunJournal, AuthorizationRequest) {
	t.Helper()
	manifest := `{"plan":{"steps":[{"id":"fetch","method":"GET","url":"https://x.test/{{ input.id }}","headers":{}}]}}`
	hash, signed, publicKey := signedManifest(t, manifest)
	cache := NewArtifactCache()
	if err := cache.Push(hash, signed, publicKey); err != nil {
		t.Fatal(err)
	}
	journal := NewMemoryRunJournal()
	row, err := journal.RecordInput("run-1", 1, json.RawMessage(`{"id":"42"}`), nil)
	if err != nil {
		t.Fatal(err)
	}
	return cache, journal, AuthorizationRequest{NodeVersionHash: hash, RunID: "run-1", StepSeq: 1, StepID: "fetch", StepInputDigest: row.Digest, CanonicalizedRequest: json.RawMessage(`{"worker":true}`)}
}

func TestAuthorizeDeniesAbsentStep(t *testing.T) {
	cache, journal, request := setupAuthorization(t)
	request.StepID = "absent"
	decision := Authorize(cache, journal, request)
	if decision.ChecksPassed || decision.StepFound {
		t.Fatalf("absent step was not denied: %+v", decision)
	}
}

func TestAuthorizeDeniesDigestMismatch(t *testing.T) {
	cache, journal, request := setupAuthorization(t)
	request.StepInputDigest = "sha256:wrong"
	decision := Authorize(cache, journal, request)
	if decision.ChecksPassed || decision.DigestMatched {
		t.Fatalf("digest mismatch was not denied: %+v", decision)
	}
}

func TestAuthorizeReturnsBothCanonicalRequests(t *testing.T) {
	cache, journal, request := setupAuthorization(t)
	decision := Authorize(cache, journal, request)
	if !decision.ChecksPassed || len(decision.RenderedRequest) == 0 || !bytes.Equal(decision.SubmittedRequest, request.CanonicalizedRequest) {
		t.Fatalf("unexpected decision: %+v", decision)
	}
}

// Regression for a real gap caught in review: Authorize used to hardcode a
// nil "previous" context when re-rendering, but a step's URL/header/body
// templates can reference {{ response.x }}, which the Python interpreter
// binds to the PREVIOUS step's mapped output -- exactly what
// tests/fixtures/plans/valid/cursor.json does for pagination
// ("cursor": "{{ response.next_cursor }}"). Reproduce that fixture's shape
// here and confirm the proxy's independent re-render actually incorporates
// the journaled previous-step context instead of silently rendering empty.
func TestAuthorizeUsesJournaledPreviousContext(t *testing.T) {
	manifest := `{"hosts":["api.example.com"],"steps":[{"id":"list","method":"GET","url":"https://api.example.com/items","headers":{},"query":{"account":"{{ input.account.id }}","cursor":"{{ response.next_cursor }}"}}]}`
	hash, signed, publicKey := signedManifest(t, manifest)
	cache := NewArtifactCache()
	if err := cache.Push(hash, signed, publicKey); err != nil {
		t.Fatal(err)
	}
	journal := NewMemoryRunJournal()
	row, err := journal.RecordInput(
		"run-1", 2,
		json.RawMessage(`{"account":{"id":"acct-1"}}`),
		json.RawMessage(`{"next_cursor":"page-2-cursor-abc"}`),
	)
	if err != nil {
		t.Fatal(err)
	}
	request := AuthorizationRequest{
		NodeVersionHash: hash, RunID: "run-1", StepSeq: 2, StepID: "list",
		StepInputDigest: row.Digest, CanonicalizedRequest: json.RawMessage(`{"worker":true}`),
	}
	decision := Authorize(cache, journal, request)
	if !decision.ChecksPassed {
		t.Fatalf("expected checks to pass: %+v", decision)
	}
	want := `{"method":"GET","url":"https://api.example.com/items?account=acct-1&cursor=page-2-cursor-abc","headers":{},"body":null}`
	if string(decision.RenderedRequest) != want {
		t.Fatalf("got  %s\nwant %s", decision.RenderedRequest, want)
	}
}

func TestNoForbiddenIdentifiers(t *testing.T) {
	for _, identifier := range []string{
		"SkipVerify", "IsTrusted", "TrustedHost", "isBypass", "dangerFullAccess",
		"skip_verify", "DANGER_FULL_ACCESS",
	} {
		t.Run(identifier, func(t *testing.T) {
			source := []byte("package synthetic\nvar " + identifier + " bool\n")
			if got := findForbiddenIdentifier(source); got == "" {
				t.Fatalf("identifier %q was not detected", identifier)
			}
		})
	}
	for _, source := range []string{
		"package synthetic\nvar Truster bool\n",
		"package synthetic\n// do not trust this input\nvar safe bool\n",
		"package synthetic\nvar warning = `IsTrusted`\n",
	} {
		if got := findForbiddenIdentifier([]byte(source)); got != "" {
			t.Errorf("ordinary source flagged forbidden identifier %q", got)
		}
	}

	err := filepath.WalkDir(".", func(path string, entry os.DirEntry, err error) error {
		if err != nil {
			return err
		}
		if entry.IsDir() || strings.HasSuffix(path, "_test.go") || !strings.HasSuffix(path, ".go") {
			return nil
		}
		contents, err := os.ReadFile(path)
		if err != nil {
			return err
		}
		if match := findForbiddenIdentifier(contents); match != "" {
			t.Errorf("%s contains forbidden identifier %q", path, match)
		}
		return nil
	})
	if err != nil {
		t.Fatal(err)
	}
}

func findForbiddenIdentifier(source []byte) string {
	var scan scanner.Scanner
	scan.Init(token.NewFileSet().AddFile("", -1, len(source)), source, nil, 0)
	for {
		_, tok, identifier := scan.Scan()
		if tok == token.EOF {
			return ""
		}
		if tok != token.IDENT {
			continue
		}
		parts := identifierParts(identifier)
		for i, part := range parts {
			if part == "bypass" || part == "trusted" ||
				i+1 < len(parts) && part == "skip" && parts[i+1] == "verify" ||
				i+2 < len(parts) && part == "danger" && parts[i+1] == "full" && parts[i+2] == "access" {
				return identifier
			}
		}
	}
}

func identifierParts(identifier string) []string {
	// Split only lower-to-upper camel-case boundaries. Acronym-heavy names without
	// underscores (for example, DANGERFullAccess) are a known limitation.
	var parts []string
	var part strings.Builder
	previousLower := false
	flush := func() {
		if part.Len() != 0 {
			parts = append(parts, part.String())
			part.Reset()
		}
	}
	for _, r := range identifier {
		if r == '_' {
			flush()
			previousLower = false
			continue
		}
		if unicode.IsUpper(r) && previousLower {
			flush()
		}
		part.WriteRune(unicode.ToLower(r))
		previousLower = unicode.IsLower(r)
	}
	flush()
	return parts
}
