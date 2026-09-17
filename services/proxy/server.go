package proxy

import (
	"encoding/json"
	"errors"
	"io"
	"net/http"
	"strings"
)

const authorizationPath = "/v1/authorize"

// Server exposes POST /v1/authorize. Policy, secret bindings, credential
// storage, and transport are injected by the caller as the deliberate v1
// scope boundary until artifact runtime limits and infrastructure exist.
type Server struct {
	Cache     *ArtifactCache
	Journal   RunJournal
	Policy    ForwardPolicy
	Bindings  SecretBindings
	Store     *CredentialStore
	Transport Transport
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

	authorization, err := decodeAuthorizationRequest(request.Body)
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

	response, event, err := Forward(decision, server.Policy, server.Bindings, server.Store, server.Transport)
	if event != nil {
		// Authorization succeeded, but the upstream response violated an
		// enforced proxy policy; Bad Gateway identifies that boundary.
		writeJSON(writer, http.StatusBadGateway, event)
		return
	}
	if err != nil {
		writeJSON(writer, http.StatusBadGateway, map[string]string{"error": "upstream request failed"})
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

func writeJSON(writer http.ResponseWriter, status int, value any) {
	writer.Header().Set("Content-Type", "application/json")
	writer.WriteHeader(status)
	_ = json.NewEncoder(writer).Encode(value)
}
