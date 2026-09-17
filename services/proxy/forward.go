package proxy

import (
	"bytes"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net/url"
	"strings"
)

type OutboundRequest struct {
	Method  string
	URL     string
	Headers map[string]string
	Body    []byte
}

type OutboundResponse struct {
	Status  int
	Headers map[string]string
	Body    []byte
}

// Transport sends one request and returns the response with its body fully
// read. maxResponseBytes is the caller's configured limit (ForwardPolicy.
// MaxResponseBytes) -- a real implementation MUST bound its read using it
// (BoundedRead below does this correctly) rather than reading an unbounded
// response into memory before Forward gets a chance to check its length.
// Forward still checks the returned length itself as defense-in-depth
// against a Transport that ignores this contract, but that check runs
// after the fact and cannot undo memory or bandwidth already spent -- the
// mock transports used in this package's own tests fully buffer their
// (small, fixture-sized) bodies and rely on that defense-in-depth check,
// which is fine for tests but is not the contract a real transport gets to
// rely on.
type Transport func(request OutboundRequest, maxResponseBytes int) (OutboundResponse, error)

// BoundedRead reads at most maxBytes from r into memory, refusing to
// buffer more than that even if r would produce more. Reads one byte past
// the limit to distinguish "exactly the limit" from "more than the limit"
// without needing the source's total length up front, mirroring
// packages/interpreter/python/ferrule_interpreter/interpreter.py's
// `raw.read(MAX_RESPONSE_BODY_BYTES + 1)` technique. A real Transport
// implementation should call this on the live response body instead of
// io.ReadAll, so an oversized response is refused during acquisition, not
// only after it has already been fully downloaded.
func BoundedRead(r io.Reader, maxBytes int) ([]byte, error) {
	data, err := io.ReadAll(io.LimitReader(r, int64(maxBytes)+1))
	if err != nil {
		return nil, err
	}
	if len(data) > maxBytes {
		return nil, fmt.Errorf("response exceeds %d byte limit", maxBytes)
	}
	return data, nil
}

// ForwardPolicy is supplied by the caller until full node manifests produce
// SPEC.md section 5's runtime_limits block. This is a deliberate temporary
// milestone scope decision, not an alternate source of artifact authority.
type ForwardPolicy struct {
	MaxRedirects        int
	MaxResponseBytes    int
	AllowedContentTypes []string
}

// Forward sends an independently rendered, already-authorized request and
// enforces redirect and response bounds without inspecting response body
// text. It takes the Decision returned by Authorize -- not a second,
// separately-suppliable AuthorizationRequest -- so a caller cannot forward
// step A's rendered request while attributing SecurityEvents to step B's
// identifiers; there is no second identity parameter left to disagree with
// the Decision.
//
// The real gate here is decision.verified, an unexported field only
// Authorize's success path can set -- ChecksPassed alone is checked too
// for a clearer error message, but a caller outside this package cannot
// set ChecksPassed to true and have Forward honor it, because it cannot
// set verified at all. This closes a gap tracked during the 2c audit:
// previously any caller could forge Decision{ChecksPassed: true, ...}
// and obtain full secret resolution and forwarding with no artifact
// lookup, journal check, host check, or byte comparison ever having run.
func Forward(decision Decision, policy ForwardPolicy, bindings SecretBindings, store *CredentialStore, transport Transport) (OutboundResponse, *SecurityEvent, error) {
	if !decision.ChecksPassed || !decision.verified {
		return OutboundResponse{}, nil, errors.New("cannot forward an unauthorized request")
	}
	if transport == nil {
		return OutboundResponse{}, nil, errors.New("transport is nil")
	}
	resolved, secretValues, err := ResolveSecrets(decision.RenderedRequest, bindings, store)
	if err != nil {
		return OutboundResponse{}, nil, err
	}
	outbound, err := decodeOutboundRequest(resolved)
	if err != nil {
		return OutboundResponse{}, nil, fmt.Errorf("decode rendered request: %w", err)
	}
	originalURL, err := url.Parse(outbound.URL)
	if err != nil || originalURL.Hostname() == "" {
		return OutboundResponse{}, nil, errors.New("rendered request URL is invalid")
	}

	redirects := 0
	for {
		response, err := transport(outbound, policy.MaxResponseBytes)
		if err != nil {
			// The transport received the resolved (secret-bearing) outbound
			// request, and a real HTTP client's error text commonly echoes
			// the request URL or other details. Redact before returning so
			// a transport that does this (buggy or malicious) can't hand a
			// raw credential back to the caller through an error message.
			return OutboundResponse{}, nil, errors.New(string(Redact([]byte(err.Error()), secretValues)))
		}
		location := headerValue(response.Headers, "Location")
		if response.Status >= 300 && response.Status < 400 && location != "" {
			currentURL, err := url.Parse(outbound.URL)
			if err != nil {
				return OutboundResponse{}, nil, fmt.Errorf("parse current request URL: %w", err)
			}
			reference, err := url.Parse(location)
			if err != nil {
				return OutboundResponse{}, nil, fmt.Errorf("parse redirect location: %w", err)
			}
			target := currentURL.ResolveReference(reference)
			// Compare the full origin (scheme + host + port), not just the
			// hostname. Hostname-only comparison would treat an
			// https -> http redirect to the identical hostname as
			// "same-host" and follow it -- a scheme downgrade that, once
			// milestone 2c injects real credentials into headers that are
			// carried across a followed redirect, becomes a plaintext
			// credential-leak vector. Denying it here, where the host
			// comparison already lives, is cheaper than remembering to
			// special-case it once secrets exist.
			if !strings.EqualFold(target.Scheme, originalURL.Scheme) || !strings.EqualFold(target.Host, originalURL.Host) {
				return forwardDenied(decision, secretValues, "cross_host_redirect", fmt.Sprintf("redirect target origin %q differs from authorized origin %q", target.Scheme+"://"+target.Host, originalURL.Scheme+"://"+originalURL.Host))
			}
			if redirects >= policy.MaxRedirects {
				return forwardDenied(decision, secretValues, "request_budget_exceeded", "same-host redirect budget exceeded")
			}
			redirects++
			// Deliberate v1 limitation: redirects preserve the prior method,
			// headers, and body instead of applying status-specific HTTP rewrites.
			outbound.URL = target.String()
			continue
		}

		if len(response.Body) > policy.MaxResponseBytes {
			return forwardDenied(decision, secretValues, "response_too_large", fmt.Sprintf("response body has %d bytes; limit is %d", len(response.Body), policy.MaxResponseBytes))
		}
		if len(policy.AllowedContentTypes) > 0 && !contentTypeAllowed(headerValue(response.Headers, "Content-Type"), policy.AllowedContentTypes) {
			return forwardDenied(decision, secretValues, "disallowed_content_type", fmt.Sprintf("response content type %q is not allowed", headerValue(response.Headers, "Content-Type")))
		}
		response.Body = Redact(response.Body, secretValues)
		for name, value := range response.Headers {
			response.Headers[name] = string(Redact([]byte(value), secretValues))
		}
		return response, nil, nil
	}
}

func decodeOutboundRequest(rendered []byte) (OutboundRequest, error) {
	var value struct {
		Method  string            `json:"method"`
		URL     string            `json:"url"`
		Headers map[string]string `json:"headers"`
		Body    json.RawMessage   `json:"body"`
	}
	if err := json.Unmarshal(rendered, &value); err != nil {
		return OutboundRequest{}, err
	}
	body := []byte(value.Body)
	if bytes.Equal(body, []byte("null")) {
		body = nil
	}
	return OutboundRequest{Method: value.Method, URL: value.URL, Headers: value.Headers, Body: body}, nil
}

func headerValue(headers map[string]string, name string) string {
	for key, value := range headers {
		if strings.EqualFold(key, name) {
			return value
		}
	}
	return ""
}

func contentTypeAllowed(contentType string, allowed []string) bool {
	mediaType := strings.TrimSpace(strings.SplitN(contentType, ";", 2)[0])
	for _, candidate := range allowed {
		if strings.EqualFold(mediaType, strings.TrimSpace(candidate)) {
			return true
		}
	}
	return false
}

// forwardDenied builds a denial after secrets have already been resolved
// (every call site in Forward runs after ResolveSecrets). reason is built
// from response metadata that an upstream fully controls -- a redirect's
// Location host, a Content-Type header value -- and an upstream that has
// just received a resolved credential can set either of these to literally
// echo it back, landing the raw secret in this event's Reason otherwise.
// Always redact secretValues out of reason before it leaves this function.
func forwardDenied(decision Decision, secretValues []string, code, reason string) (OutboundResponse, *SecurityEvent, error) {
	return OutboundResponse{}, &SecurityEvent{
		Code: code, Reason: string(Redact([]byte(reason), secretValues)),
		NodeVersionHash: decision.NodeVersionHash, RunID: decision.RunID,
		StepSeq: decision.StepSeq, StepID: decision.StepID,
	}, nil
}
