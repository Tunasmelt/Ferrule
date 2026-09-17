package proxy

import "encoding/json"

// AuthorizationRequest carries the worker's already-canonical JSON request.
// Milestone 2b will compare it with Decision.RenderedRequest.
type AuthorizationRequest struct {
	NodeVersionHash      string
	RunID                string
	StepSeq              int
	StepID               string
	StepInputDigest      string
	CanonicalizedRequest json.RawMessage
}

type Decision struct {
	ChecksPassed     bool
	ArtifactFound    bool
	StepFound        bool
	JournalFound     bool
	DigestMatched    bool
	RenderedRequest  json.RawMessage
	SubmittedRequest json.RawMessage
	Reason           string
}

func Authorize(cache *ArtifactCache, journal RunJournal, request AuthorizationRequest) Decision {
	decision := Decision{SubmittedRequest: append(json.RawMessage(nil), request.CanonicalizedRequest...)}
	manifest, ok := cache.Get(request.NodeVersionHash)
	if !ok {
		decision.Reason = "artifact not found"
		return decision
	}
	decision.ArtifactFound = true
	step, ok := findStep(manifest, request.StepID)
	if !ok {
		decision.Reason = "step not found"
		return decision
	}
	decision.StepFound = true
	entry, ok := journal.LookupInput(request.RunID, request.StepSeq)
	if !ok {
		decision.Reason = "journal input not found"
		return decision
	}
	decision.JournalFound = true
	if entry.Digest != request.StepInputDigest {
		decision.Reason = "step input digest mismatch"
		return decision
	}
	decision.DigestMatched = true
	input, err := decodeJSONMap(entry.Input)
	if err != nil {
		decision.Reason = "journal input is invalid"
		return decision
	}
	rendered, err := RenderRequest(step, input, nil)
	if err != nil {
		decision.Reason = err.Error()
		return decision
	}
	decision.RenderedRequest = rendered
	decision.ChecksPassed = true
	return decision
}

func findStep(manifest map[string]any, stepID string) (map[string]any, bool) {
	// A full node manifest (SPEC.md section 5) nests the plan under a "plan"
	// key. Milestone 1a's bare plan document -- the shape actually produced,
	// schema-checked and executed everywhere else in this codebase today --
	// has "steps" at its own top level instead, with no "plan" wrapper at
	// all. Treat the manifest itself as the plan when no "plan" key exists,
	// so authorization works against the plan documents this project
	// actually has right now, not only the future full-manifest shape.
	plan, ok := manifest["plan"].(map[string]any)
	if !ok {
		plan = manifest
	}
	steps, ok := plan["steps"].([]any)
	if !ok {
		return nil, false
	}
	for _, value := range steps {
		step, ok := value.(map[string]any)
		if ok && step["id"] == stepID {
			return step, true
		}
	}
	return nil, false
}
