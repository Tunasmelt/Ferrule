package proxy

import (
	"encoding/json"
	"testing"
)

// Reproduces the ACTUAL plan document shape used everywhere else in this
// codebase (packages/plan-schema's schema, and the Python interpreter):
// hosts and steps both top-level, no "plan" wrapper. This is not a
// hypothetical -- it is milestone 1a's real, tested, schema-validated shape.
func TestAuthorizeAcceptsBarePlanDocumentShape(t *testing.T) {
	manifest := `{"hosts":["x.test"],"steps":[{"id":"fetch","method":"GET","url":"https://x.test/{{ input.id }}","headers":{}}]}`
	hash, signed, publicKey := signedManifest(t, manifest)
	cache := NewArtifactCache()
	if err := cache.Push(hash, signed, publicKey); err != nil {
		t.Fatal(err)
	}
	journal := NewMemoryRunJournal()
	row, err := journal.RecordInput("run-1", 1, json.RawMessage(`{"id":"42"}`))
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
