package proxy

import (
	"crypto/subtle"
	"encoding/json"
	"errors"
	"io"
	"net/http"
	"strings"
)

const authorizationPath = "/v1/authorize"

// maxAuthorizationRequestBytes bounds the /v1/authorize request body.
// Found missing during a whole-phase audit: decodeAuthorizationRequest used
// an unbounded json.Decoder directly on request.Body, so an unauthenticated
// network client could send an arbitrarily large body and impose avoidable
// memory/CPU load before the JSON decode ever fails. Matches the same
// 1 MiB convention already used for outbound response bodies
// (packages/interpreter/python/ferrule_interpreter/interpreter.py's
// MAX_RESPONSE_BODY_BYTES) for a request body that should never need to be
// large: a canonicalized_request is itself a bounded, structurally simple
// JSON envelope.
const maxAuthorizationRequestBytes = 1_048_576

// Server exposes POST /v1/authorize. Policy, secret bindings, credential
// storage, and transport are injected by the caller as the deliberate v1
// scope boundary until artifact runtime limits and infrastructure exist.
//
// AuthToken is required (ServeHTTP fails closed if it is empty, rather than
// treating an unset token as "authentication disabled") -- found missing
// during a whole-phase audit: this endpoint had no authentication at all.
// Traced concretely at the time: a network-only attacker could not forge an
// accepted request from nothing (it still needs an exact step_input_digest,
// which requires journal visibility), but the identifiers involved function
// as a de facto bearer capability rather than real authentication. This is
// a shared-secret bearer check, not a full workload-identity system --
// proportionate to there being no other auth mechanism anywhere in this
// project yet, and callers are expected to reach this endpoint over a
// private network in addition to presenting the token, not instead of it.
type Server struct {
	Cache     *ArtifactCache
	Journal   RunJournal
	Policy    ForwardPolicy
	Bindings  *SecretBindings
	Store     *CredentialStore
	Transport Transport
	AuthToken string
}

func (server *Server) Handler() http.Handler { return server }

func (server *Server) ServeHTTP(writer http.ResponseWriter, request *http.Request) {
	if request.URL.Path != authorizationPath {
		http.NotFound(writer, request)
		return
	}
	if request.Method != http.MethodPost {
		writer.Header().Set("Allow", http.MethodPost)
		writeJSON(writer, http.StatusMethodNotAllowed, map[string]string{"error": "method not allowed"})
		return
	}
	if !authorized(server.AuthToken, request.Header.Get("Authorization")) {
		writer.Header().Set("WWW-Authenticate", "Bearer")
		writeJSON(writer, http.StatusUnauthorized, map[string]string{"error": "missing or invalid authorization"})
		return
	}

	bounded := http.MaxBytesReader(writer, request.Body, maxAuthorizationRequestBytes)
	authorization, err := decodeAuthorizationRequest(bounded)
	if err != nil {
		writeJSON(writer, http.StatusBadRequest, map[string]string{"error": "invalid authorization request"})
		return
	}
	decision := Authorize(server.Cache, server.Journal, authorization)
	if !decision.ChecksPassed {
		if decision.SecurityEvent != nil {
			writeJSON(writer, http.StatusForbidden, decision.SecurityEvent)
		} else {
			writeJSON(writer, http.StatusForbidden, map[string]string{"reason": decision.Reason})
		}
		return
	}

	// The artifact's own signed runtime_limits (if it declares any) can only
	// tighten server.Policy, never widen it -- see MergeForwardPolicy and
	// Decision.ArtifactLimits' doc comments.
	policy := MergeForwardPolicy(server.Policy, decision.ArtifactLimits)
	response, event, err := Forward(decision, policy, server.Bindings, server.Store, server.Transport)
	if event != nil {
		// Authorization succeeded, but the upstream response violated an
		// enforced proxy policy; Bad Gateway identifies that boundary.
		writeJSON(writer, http.StatusBadGateway, event)
		return
	}
	if err != nil {
		// ResolveSecrets returns a *FailureClassError (SPEC.md section 7)
		// when a plan's secret has no binding or its bound credential is
		// missing/deleted. Found missing during milestone 2d's own review:
		// this used to be discarded into the same generic message as any
		// other Forward error, so a caller had no way to distinguish "the
		// credential was deleted, don't retry" from a transient network
		// failure -- exactly the distinction failure classes exist to
		// carry. 403 matches the pre-Forward denial responses above: this
		// is an authorization-shaped failure, not an upstream problem.
		var failure *FailureClassError
		if errors.As(err, &failure) {
			writeJSON(writer, http.StatusForbidden, map[string]string{"failure_class": failure.Class, "error": failure.Error()})
			return
		}
		// A network/connectivity failure from the transport (SPEC.md section
		// 7: "transient" or "timeout", both retryable) -- found missing
		// during a whole-phase audit alongside the auth case above. Errors
		// that reach here unclassified (a decode failure, a nil transport,
		// an invalid rendered URL) are internal proxy faults SPEC's failure
		// classes don't model; they stay in the generic bucket rather than
		// being mislabeled with a class that doesn't fit them.
		var transportErr *TransportError
		if errors.As(err, &transportErr) {
			writeJSON(writer, http.StatusBadGateway, map[string]string{"failure_class": transportErr.Class, "error": transportErr.Error()})
			return
		}
		writeJSON(writer, http.StatusBadGateway, map[string]string{"error": "upstream request failed"})
		return
	}
	// A response is about to be fully delivered -- from here on this
	// (run_id, step_seq) must never be authorized again (see
	// JournalEntry.Consumed's doc comment). Mark it before writing the
	// response, not after: if the write itself fails partway through,
	// the caller may still have received some or all of the side effect
	// already having happened upstream, so failing open here (leaving it
	// replayable) would be the wrong default.
	if err := server.Journal.MarkConsumed(authorization.RunID, authorization.StepSeq); err != nil {
		writeJSON(writer, http.StatusInternalServerError, map[string]string{"error": "failed to record run completion"})
		return
	}
	for name, value := range response.Headers {
		// Forward's redaction can change response.Body's length relative to
		// what the upstream declared (a secret occurrence and "[REDACTED]"
		// are rarely the same length), so the upstream's own Content-Length
		// is stale by the time it would reach here -- confirmed directly:
		// writing a body whose actual length differs from a copied,
		// smaller stale Content-Length makes Go's own net/http client
		// read zero bytes and report "unexpected EOF" for the entire
		// response, not a truncated one. Skip it (and Transfer-Encoding,
		// which is equally stale once BoundedRead has already fully
		// buffered the body into memory) and let net/http compute the
		// correct Content-Length itself from what is actually written
		// below.
		if strings.EqualFold(name, "Content-Length") || strings.EqualFold(name, "Transfer-Encoding") {
			continue
		}
		writer.Header().Set(name, value)
	}
	writer.WriteHeader(response.Status)
	_, _ = writer.Write(response.Body)
}

type authorizationWireRequest struct {
	NodeVersionHash      string          `json:"node_version_hash"`
	RunID                string          `json:"run_id"`
	StepSeq              int             `json:"step_seq"`
	StepID               string          `json:"step_id"`
	StepInputDigest      string          `json:"step_input_digest"`
	CanonicalizedRequest json.RawMessage `json:"canonicalized_request"`
}

func decodeAuthorizationRequest(body io.Reader) (AuthorizationRequest, error) {
	var wire authorizationWireRequest
	decoder := json.NewDecoder(body)
	if err := decoder.Decode(&wire); err != nil {
		return AuthorizationRequest{}, err
	}
	var extra json.RawMessage
	if err := decoder.Decode(&extra); !errors.Is(err, io.EOF) {
		return AuthorizationRequest{}, errors.New("request body must contain one JSON value")
	}
	if wire.NodeVersionHash == "" || wire.RunID == "" || wire.StepSeq <= 0 || wire.StepID == "" || wire.StepInputDigest == "" || len(wire.CanonicalizedRequest) == 0 || string(wire.CanonicalizedRequest) == "null" {
		return AuthorizationRequest{}, errors.New("required field is missing")
	}
	return AuthorizationRequest{
		NodeVersionHash: wire.NodeVersionHash, RunID: wire.RunID, StepSeq: wire.StepSeq,
		StepID: wire.StepID, StepInputDigest: wire.StepInputDigest,
		CanonicalizedRequest: wire.CanonicalizedRequest,
	}, nil
}

// authorized fails closed: an empty configured token never matches any
// presented header, including another empty one, so a Server with
// AuthToken unset denies every request rather than silently accepting all
// of them. Uses a constant-time comparison so response timing cannot be
// used to guess the token byte-by-byte.
func authorized(configuredToken, presentedHeader string) bool {
	if configuredToken == "" {
		return false
	}
	const prefix = "Bearer "
	if !strings.HasPrefix(presentedHeader, prefix) {
		return false
	}
	presented := strings.TrimPrefix(presentedHeader, prefix)
	return subtle.ConstantTimeCompare([]byte(presented), []byte(configuredToken)) == 1
}

func writeJSON(writer http.ResponseWriter, status int, value any) {
	writer.Header().Set("Content-Type", "application/json")
	writer.WriteHeader(status)
	_ = json.NewEncoder(writer).Encode(value)
}
