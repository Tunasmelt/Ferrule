package proxy

import (
	"encoding/json"
	"testing"
)

func authorizationFixture(t *testing.T, manifest, submitted string) (*ArtifactCache, *MemoryRunJournal, AuthorizationRequest) {
	t.Helper()
	hash, signed, publicKey := signedManifest(t, manifest)
	cache := NewArtifactCache()
	if err := cache.Push(hash, signed, publicKey); err != nil {
		t.Fatal(err)
	}
	journal := NewMemoryRunJournal()
	entry, err := journal.RecordInput("run-1", 1, json.RawMessage(`{"id":"42"}`), nil)
	if err != nil {
		t.Fatal(err)
	}
	return cache, journal, AuthorizationRequest{
		NodeVersionHash:      hash,
		RunID:                "run-1",
		StepSeq:              1,
		StepID:               "fetch",
		StepInputDigest:      entry.Digest,
		CanonicalizedRequest: json.RawMessage(submitted),
	}
}

func TestAuthorizeDeniesSubmittedURLMismatch(t *testing.T) {
	manifest := `{"hosts":["x.test"],"steps":[{"id":"fetch","method":"GET","url":"https://x.test/{{ input.id }}","headers":{}}]}`
	cache, journal, request := authorizationFixture(t, manifest, `{"method":"GET","url":"https://x.test/other","headers":{},"body":null}`)

	decision := Authorize(cache, journal, request)

	if decision.ChecksPassed || decision.SecurityEvent == nil || decision.SecurityEvent.Code != "request_mismatch" {
		t.Fatalf("URL mismatch was not denied with a security event: %+v", decision)
	}
}

func TestAuthorizeDeniesHostAbsentFromPlanHosts(t *testing.T) {
	manifest := `{"capabilities":{"hosts":["outside.test"]},"plan":{"hosts":["inside.test"],"steps":[{"id":"fetch","method":"GET","url":"https://outside.test/items","headers":{}}]}}`
	submitted := `{"method":"GET","url":"https://outside.test/items","headers":{},"body":null}`
	cache, journal, request := authorizationFixture(t, manifest, submitted)

	decision := Authorize(cache, journal, request)

	if decision.ChecksPassed || decision.SecurityEvent == nil || decision.SecurityEvent.Code != "undeclared_host" {
		t.Fatalf("capability host widened plan authorization: %+v", decision)
	}
}

func TestAuthorizeDeniesSubmittedMethodMismatch(t *testing.T) {
	manifest := `{"hosts":["x.test"],"steps":[{"id":"fetch","method":"GET","url":"https://x.test/items","headers":{}}]}`
	submitted := `{"method":"DELETE","url":"https://x.test/items","headers":{},"body":null}`
	cache, journal, request := authorizationFixture(t, manifest, submitted)

	decision := Authorize(cache, journal, request)

	// The exact canonical-request comparison catches method divergence; there
	// is intentionally no second method-specific authorization path.
	if decision.ChecksPassed || decision.SecurityEvent == nil || decision.SecurityEvent.Code != "request_mismatch" {
		t.Fatalf("method mismatch was not denied by request comparison: %+v", decision)
	}
}

func TestAuthorizeAcceptsMatchingRequest(t *testing.T) {
	manifest := `{"hosts":["X.TEST"],"steps":[{"id":"fetch","method":"GET","url":"https://x.test/{{ input.id }}","headers":{}}]}`
	submitted := `{"method":"GET","url":"https://x.test/42","headers":{},"body":null}`
	cache, journal, request := authorizationFixture(t, manifest, submitted)

	decision := Authorize(cache, journal, request)

	if !decision.ChecksPassed || decision.SecurityEvent != nil {
		t.Fatalf("matching request was denied: %+v", decision)
	}
}
