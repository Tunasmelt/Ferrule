package proxy

import (
	"bytes"
	"encoding/json"
	"errors"
	"fmt"
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

type Transport func(OutboundRequest) (OutboundResponse, error)

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
func Forward(decision Decision, policy ForwardPolicy, transport Transport) (OutboundResponse, *SecurityEvent, error) {
	if !decision.ChecksPassed {
		return OutboundResponse{}, nil, errors.New("cannot forward an unauthorized request")
	}
	if transport == nil {
		return OutboundResponse{}, nil, errors.New("transport is nil")
	}
	outbound, err := decodeOutboundRequest(decision.RenderedRequest)
	if err != nil {
		return OutboundResponse{}, nil, fmt.Errorf("decode rendered request: %w", err)
	}
	originalURL, err := url.Parse(outbound.URL)
	if err != nil || originalURL.Hostname() == "" {
		return OutboundResponse{}, nil, errors.New("rendered request URL is invalid")
	}

	redirects := 0
	for {
		response, err := transport(outbound)
		if err != nil {
			return OutboundResponse{}, nil, err
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
				return forwardDenied(decision, "cross_host_redirect", fmt.Sprintf("redirect target origin %q differs from authorized origin %q", target.Scheme+"://"+target.Host, originalURL.Scheme+"://"+originalURL.Host))
			}
			if redirects >= policy.MaxRedirects {
				return forwardDenied(decision, "request_budget_exceeded", "same-host redirect budget exceeded")
			}
			redirects++
			// Deliberate v1 limitation: redirects preserve the prior method,
			// headers, and body instead of applying status-specific HTTP rewrites.
			outbound.URL = target.String()
			continue
		}

		if len(response.Body) > policy.MaxResponseBytes {
			return forwardDenied(decision, "response_too_large", fmt.Sprintf("response body has %d bytes; limit is %d", len(response.Body), policy.MaxResponseBytes))
		}
		if len(policy.AllowedContentTypes) > 0 && !contentTypeAllowed(headerValue(response.Headers, "Content-Type"), policy.AllowedContentTypes) {
			return forwardDenied(decision, "disallowed_content_type", fmt.Sprintf("response content type %q is not allowed", headerValue(response.Headers, "Content-Type")))
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

func forwardDenied(decision Decision, code, reason string) (OutboundResponse, *SecurityEvent, error) {
	return OutboundResponse{}, &SecurityEvent{
		Code: code, Reason: reason,
		NodeVersionHash: decision.NodeVersionHash, RunID: decision.RunID,
		StepSeq: decision.StepSeq, StepID: decision.StepID,
	}, nil
}
