package proxy

import (
	"encoding/json"
	"testing"
)

// Reproduces the ACTUAL plan document shape used everywhere else in this
// codebase (packages/plan-schema's schema, and the Python interpreter):
// hosts and steps both top-level, no "plan" wrapper. This is not a
// hypothetical -- it is milestone 1a's real, tested, schema-validated shape.
//
// This only proves findStep locates a step in the bare shape -- the
// submitted request below is a stub that fails milestone 2b's byte
// comparison, so this does NOT prove full authorization succeeds against a
// bare-plan document. That's covered separately by
// TestAuthorizeAcceptsMatchingRequest in authorize_test.go, which uses this
// same bare shape end to end. Caught in the 2b audit: this test's original
// name ("Accepts...") overclaimed what it verifies.
func TestFindStepAcceptsBarePlanDocumentShape(t *testing.T) {
	manifest := `{"hosts":["x.test"],"steps":[{"id":"fetch","method":"GET","url":"https://x.test/{{ input.id }}","headers":{}}]}`
	hash, signed, publicKey := signedManifest(t, manifest)
	cache := NewArtifactCache()
	if err := cache.Push(hash, signed, publicKey); err != nil {
		t.Fatal(err)
	}
	journal := NewMemoryRunJournal()
	row, err := journal.RecordInput("run-1", 1, hash, "fetch", json.RawMessage(`{"id":"42"}`), nil)
	if err != nil {
		t.Fatal(err)
	}
	request := AuthorizationRequest{
		NodeVersionHash: hash, RunID: "run-1", StepSeq: 1, StepID: "fetch",
		StepInputDigest: row.Digest, CanonicalizedRequest: json.RawMessage(`{"worker":true}`),
	}
	decision := Authorize(cache, journal, request)
	if !decision.StepFound {
		t.Fatalf("real bare-plan-document shape: step not found (Reason=%q) -- findStep only checks manifest[\"plan\"][\"steps\"], but the actual plan documents produced elsewhere in this codebase (packages/plan-schema, the Python interpreter) put \"steps\" at the top level with no \"plan\" wrapper", decision.Reason)
	}
}
