package proxy

import (
	"bytes"
	"encoding/json"
	"fmt"
	"net/url"
	"strings"
)

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
	// Identity fields, copied from the AuthorizationRequest that produced
	// this Decision. Forward() reads these instead of taking a second,
	// separately-suppliable AuthorizationRequest parameter -- a caller
	// cannot authorize step A and then forward it while attributing
	// SecurityEvents to step B's identifiers, because there is no second
	// parameter left to disagree with the Decision.
	NodeVersionHash string
	RunID           string
	StepSeq         int
	StepID          string

	ChecksPassed     bool
	ArtifactFound    bool
	StepFound        bool
	JournalFound     bool
	DigestMatched    bool
	RenderedRequest  json.RawMessage
	SubmittedRequest json.RawMessage
	Reason           string
	SecurityEvent    *SecurityEvent

	// verified is deliberately unexported. Go forbids setting an
	// unexported struct field from outside its declaring package, so a
	// caller in a different package (a real orchestrator or HTTP handler,
	// once one exists) cannot construct a Decision with ChecksPassed:
	// true and have Forward act on it -- the only way to produce a
	// Decision with verified set is to call Authorize and reach its
	// success path. Code inside this package (including this package's
	// own tests, which legitimately need to fabricate decisions to unit
	// test Forward in isolation) can still set it directly; that is the
	// intended boundary, not a bypass of it. Tracked as a gap in the 2c
	// audit and closed here before 2d needs a real caller to trust this.
	verified bool
}

func Authorize(cache *ArtifactCache, journal RunJournal, request AuthorizationRequest) Decision {
	decision := Decision{
		NodeVersionHash:  request.NodeVersionHash,
		RunID:            request.RunID,
		StepSeq:          request.StepSeq,
		StepID:           request.StepID,
		SubmittedRequest: append(json.RawMessage(nil), request.CanonicalizedRequest...),
	}
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
	envelope, err := decodeJSONMap(entry.Context)
	if err != nil {
		decision.Reason = "journal input is invalid"
		return decision
	}
	input, ok := envelope["input"].(map[string]any)
	if !ok {
		input = map[string]any{}
	}
	previous, ok := envelope["previous"].(map[string]any)
	if !ok {
		previous = map[string]any{}
	}
	rendered, err := RenderRequest(step, input, previous)
	if err != nil {
		decision.Reason = err.Error()
		return decision
	}
	decision.RenderedRequest = rendered
	var renderedRequest struct {
		URL string `json:"url"`
	}
	// A decode failure here means RenderRequest produced malformed JSON, not
	// that a host is undeclared -- give it its own code so a SecurityEvent
	// consumer (drift/alerting, later phases) doesn't miscount an internal
	// rendering fault as a host-authorization violation.
	if unmarshalErr := json.Unmarshal(rendered, &renderedRequest); unmarshalErr != nil {
		return deny(decision, "invalid_rendered_request", "rendered request is not valid JSON: "+unmarshalErr.Error())
	}
	host := ""
	if parsedURL, parseErr := url.Parse(renderedRequest.URL); parseErr == nil {
		host = parsedURL.Hostname()
	}
	if host == "" || !hostDeclared(manifest, host) {
		return deny(decision, "undeclared_host", fmt.Sprintf("rendered request host %q is not declared in plan hosts", host))
	}
	if !bytes.Equal(decision.RenderedRequest, decision.SubmittedRequest) {
		return deny(decision, "request_mismatch", requestMismatchReason(rendered, decision.SubmittedRequest))
	}
	decision.ChecksPassed = true
	decision.verified = true
	return decision
}

func deny(decision Decision, code, reason string) Decision {
	decision.Reason = reason
	decision.SecurityEvent = &SecurityEvent{
		Code: code, Reason: reason,
		NodeVersionHash: decision.NodeVersionHash, RunID: decision.RunID,
		StepSeq: decision.StepSeq, StepID: decision.StepID,
	}
	return decision
}

func hostDeclared(manifest map[string]any, host string) bool {
	// Hosts belong to the same effective plan document as steps. In a full
	// manifest this intentionally ignores capabilities.hosts, which cannot
	// widen the plan's authority.
	plan := planDocument(manifest)
	hosts, _ := plan["hosts"].([]any)
	for _, declared := range hosts {
		if value, ok := declared.(string); ok && strings.EqualFold(value, host) {
			return true
		}
	}
	return false
}

func requestMismatchReason(rendered, submitted []byte) string {
	var expected, actual map[string]json.RawMessage
	if err := json.Unmarshal(submitted, &actual); err != nil {
		return "submitted request is not valid JSON"
	}
	if err := json.Unmarshal(rendered, &expected); err == nil {
		for _, field := range []string{"method", "url", "headers", "body"} {
			if !bytes.Equal(expected[field], actual[field]) {
				return fmt.Sprintf("submitted request %s differs from independently rendered request", field)
			}
		}
	}
	return "submitted canonical request bytes differ from independently rendered request"
}

func findStep(manifest map[string]any, stepID string) (map[string]any, bool) {
	// A full node manifest (SPEC.md section 5) nests the plan under a "plan"
	// key. Milestone 1a's bare plan document -- the shape actually produced,
	// schema-checked and executed everywhere else in this codebase today --
	// has "steps" at its own top level instead, with no "plan" wrapper at
	// all. Treat the manifest itself as the plan when no "plan" key exists,
	// so authorization works against the plan documents this project
	// actually has right now, not only the future full-manifest shape.
	plan := planDocument(manifest)
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

func planDocument(manifest map[string]any) map[string]any {
	if plan, ok := manifest["plan"].(map[string]any); ok {
		return plan
	}
	return manifest
}
