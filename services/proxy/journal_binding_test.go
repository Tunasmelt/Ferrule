package proxy

import (
	"encoding/json"
	"testing"
)

// Reproduces a finding from the whole-phase audit: MemoryRunJournal is
// keyed only by (run_id, step_seq), with no binding to which artifact or
// step the journaled input was actually recorded for. If a worker submits
// a DIFFERENT node_version_hash/step_id than the one the journal entry was
// really meant for, but reuses the same (run_id, step_seq) and the correct
// digest, Authorize has no way to detect the substitution.
func TestAuthorizeRejectsJournalEntryFromWrongArtifactAndStep(t *testing.T) {
	cache := NewArtifactCache()
	journal := NewMemoryRunJournal()

	// Artifact A: a harmless read-only step.
	manifestA := `{"hosts":["x.test"],"steps":[{"id":"read","method":"GET","url":"https://x.test/read","headers":{}}]}`
	hashA, signedA, keyA := signedManifest(t, manifestA)
	if err := cache.Push(hashA, signedA, keyA); err != nil {
		t.Fatal(err)
	}

	// Artifact B: a destructive step, same host so it isn't caught by the
	// host check, but a different id/method/URL.
	manifestB := `{"hosts":["x.test"],"steps":[{"id":"delete","method":"GET","url":"https://x.test/delete-everything","headers":{}}]}`
	hashB, signedB, keyB := signedManifest(t, manifestB)
	if err := cache.Push(hashB, signedB, keyB); err != nil {
		t.Fatal(err)
	}

	// The legitimate flow: run-1/1 is journaled with empty input for
	// artifact A's "read" step.
	entry, err := journal.RecordInput("run-1", 1, hashA, "read", json.RawMessage(`{}`), nil)
	if err != nil {
		t.Fatal(err)
	}

	// The attack: submit artifact B's hash and step id, but the SAME
	// run_id/step_seq/digest that were journaled for artifact A's step.
	rendered, err := RenderRequest(map[string]any{"id": "delete", "method": "GET", "url": "https://x.test/delete-everything", "headers": map[string]any{}}, map[string]any{}, map[string]any{})
	if err != nil {
		t.Fatal(err)
	}
	request := AuthorizationRequest{
		NodeVersionHash: hashB, RunID: "run-1", StepSeq: 1, StepID: "delete",
		StepInputDigest:      entry.Digest, // borrowed from A's journal entry
		CanonicalizedRequest: rendered,
	}
	decision := Authorize(cache, journal, request)
	t.Logf("decision: ChecksPassed=%v Reason=%q SecurityEvent=%+v", decision.ChecksPassed, decision.Reason, decision.SecurityEvent)
	if decision.ChecksPassed {
		t.Fatalf("Authorize accepted a journal entry never recorded for this artifact/step: %+v", decision)
	}
	if decision.SecurityEvent == nil || decision.SecurityEvent.Code != "journal_step_mismatch" {
		t.Fatalf("expected journal_step_mismatch, got: %+v", decision)
	}

	// The legitimate request (artifact A, step "read", using its own
	// journal entry) must still be accepted -- this check must not have
	// become overly strict.
	legitimateRendered, err := RenderRequest(map[string]any{"id": "read", "method": "GET", "url": "https://x.test/read", "headers": map[string]any{}}, map[string]any{}, map[string]any{})
	if err != nil {
		t.Fatal(err)
	}
	legitimate := AuthorizationRequest{
		NodeVersionHash: hashA, RunID: "run-1", StepSeq: 1, StepID: "read",
		StepInputDigest: entry.Digest, CanonicalizedRequest: legitimateRendered,
	}
	legitimateDecision := Authorize(cache, journal, legitimate)
	if !legitimateDecision.ChecksPassed {
		t.Fatalf("legitimate matching request was denied: %+v", legitimateDecision)
	}
}
