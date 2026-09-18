package proxy

import (
	"bytes"
	"errors"
	"fmt"
	"strings"
	"testing"
)

func TestResolveSecretsFailsWithAuthAfterCredentialDeletion(t *testing.T) {
	store := &CredentialStore{}
	store.Put("broker-1", "token-value")
	rendered := []byte(`{"method":"GET","url":"https://api.example.com","headers":{"Authorization":"Bearer {{ secret.acme_erp_api_key }}"},"body":null}`)
	bindings := NewSecretBindings(map[string]string{"acme_erp_api_key": "broker-1"})

	resolved, values, err := ResolveSecrets(rendered, bindings, store)
	if err != nil || !bytes.Contains(resolved, []byte("Bearer token-value")) || len(values) != 1 || values[0] != "token-value" {
		t.Fatalf("ResolveSecrets() = (%s, %q, %v)", resolved, values, err)
	}

	store.Delete("broker-1")
	_, _, err = ResolveSecrets(rendered, bindings, store)
	var classified *FailureClassError
	if !errors.As(err, &classified) || classified.Class != "auth" {
		t.Fatalf("ResolveSecrets() error = %#v, want FailureClassError with class auth", err)
	}
}

// Regression: strconv.Quote (Go string syntax) escapes some control bytes
// as \a, \v, or \xHH, none of which are valid JSON escapes. A credential
// containing one of them would produce a request that fails to decode
// instead of being sent. ResolveSecrets must use JSON-safe escaping.
func TestResolveSecretsEscapesControlByteAsValidJSON(t *testing.T) {
	store := &CredentialStore{}
	store.Put("broker-1", "bell\x07value")
	bindings := NewSecretBindings(map[string]string{"token": "broker-1"})
	rendered := []byte(`{"method":"GET","url":"https://x.test","headers":{"Authorization":"Bearer {{ secret.token }}"},"body":null}`)

	resolved, values, err := ResolveSecrets(rendered, bindings, store)
	if err != nil {
		t.Fatalf("ResolveSecrets() error = %v", err)
	}
	outbound, err := decodeOutboundRequest(resolved)
	if err != nil {
		t.Fatalf("decodeOutboundRequest() on resolved JSON failed: %v (resolved=%s)", err, resolved)
	}
	if outbound.Headers["Authorization"] != "Bearer bell\x07value" {
		t.Fatalf("Authorization header = %q, want %q", outbound.Headers["Authorization"], "Bearer bell\x07value")
	}
	if len(values) != 1 || values[0] != "bell\x07value" {
		t.Fatalf("values = %v", values)
	}
}

func TestForwardResolvesSecretAfterAuthorization(t *testing.T) {
	store := &CredentialStore{}
	store.Put("broker-1", `token-"quoted"`)
	manifest := `{"hosts":["api.example.com"],"steps":[{"id":"fetch","method":"GET","url":"https://api.example.com/start","headers":{"Authorization":"Bearer {{ secret.acme_erp_api_key }}"}}]}`
	submitted := `{"method":"GET","url":"https://api.example.com/start","headers":{"Authorization":"Bearer {{ secret.acme_erp_api_key }}"},"body":null}`
	cache, journal, request := authorizationFixture(t, manifest, submitted)
	decision := Authorize(cache, journal, request)
	if !decision.ChecksPassed {
		t.Fatalf("Authorize() denied matching unresolved request: %+v", decision)
	}
	original := append([]byte(nil), decision.RenderedRequest...)

	var received OutboundRequest
	_, _, err := Forward(decision, ForwardPolicy{MaxResponseBytes: 100}, NewSecretBindings(map[string]string{"acme_erp_api_key": "broker-1"}), store, func(request OutboundRequest, _ int) (OutboundResponse, error) {
		received = request
		return OutboundResponse{Status: 200}, nil
	})
	if err != nil {
		t.Fatal(err)
	}
	if received.Headers["Authorization"] != `Bearer token-"quoted"` {
		t.Fatalf("transport Authorization = %q", received.Headers["Authorization"])
	}
	if !bytes.Equal(decision.RenderedRequest, original) {
		t.Fatal("Forward mutated Decision.RenderedRequest")
	}
}

func TestForwardRedactsEchoedSecretFromResponse(t *testing.T) {
	store := &CredentialStore{}
	store.Put("broker-1", "super-secret")
	decision := authorizedDecision("https://api.example.com/start")
	decision.RenderedRequest = []byte(`{"method":"GET","url":"https://api.example.com/start","headers":{"Authorization":"Bearer {{ secret.api_key }}"},"body":null}`)

	response, _, err := Forward(decision, ForwardPolicy{MaxResponseBytes: 100}, NewSecretBindings(map[string]string{"api_key": "broker-1"}), store, func(_ OutboundRequest, _ int) (OutboundResponse, error) {
		return OutboundResponse{Status: 401, Headers: map[string]string{"X-Echo": "Bearer super-secret"}, Body: []byte("rejected super-secret")}, nil
	})
	if err != nil {
		t.Fatal(err)
	}
	if bytes.Contains(response.Body, []byte("super-secret")) || response.Headers["X-Echo"] != "Bearer [REDACTED]" {
		t.Fatalf("response was not redacted: %+v", response)
	}
}

// Regression, found during the 2c audit (independently, by both a self
// review and a second Codex read-only pass): SecurityEvent.Reason for the
// post-resolution denial paths (redirect, budget, size, content-type) was
// built from response metadata an upstream fully controls -- a Content-Type
// header value, a redirect's Location host -- and was never redacted. An
// upstream that has just received a resolved credential could set either of
// those to literally echo it back, landing the raw secret in a
// caller-visible SecurityEvent even though the response body/headers
// redaction path never ran (it only runs on the success path).
func TestForwardRedactsSecretFromDenialReason(t *testing.T) {
	store := &CredentialStore{}
	store.Put("broker-1", "super-secret-value")
	decision := authorizedDecision("https://api.example.com/start")
	decision.RenderedRequest = []byte(`{"method":"GET","url":"https://api.example.com/start","headers":{"Authorization":"Bearer {{ secret.api_key }}"},"body":null}`)

	_, event, err := Forward(decision, ForwardPolicy{MaxResponseBytes: 100, AllowedContentTypes: []string{"application/json"}}, NewSecretBindings(map[string]string{"api_key": "broker-1"}), store, func(_ OutboundRequest, _ int) (OutboundResponse, error) {
		return OutboundResponse{Status: 200, Headers: map[string]string{"Content-Type": "super-secret-value"}}, nil
	})
	if err != nil {
		t.Fatal(err)
	}
	if event == nil || event.Code != "disallowed_content_type" {
		t.Fatalf("expected disallowed_content_type denial: %+v", event)
	}
	if strings.Contains(event.Reason, "super-secret-value") {
		t.Fatalf("SecurityEvent.Reason leaked the raw secret: %q", event.Reason)
	}
}

// Regression, found the same way: a transport that received the resolved
// (secret-bearing) request could format request details -- URLs and
// request/error logging commonly do -- into its returned error, which
// Forward passed through verbatim.
func TestForwardRedactsSecretFromTransportError(t *testing.T) {
	store := &CredentialStore{}
	store.Put("broker-1", "super-secret-value")
	decision := authorizedDecision("https://api.example.com/start")
	decision.RenderedRequest = []byte(`{"method":"GET","url":"https://api.example.com/start","headers":{"Authorization":"Bearer {{ secret.api_key }}"},"body":null}`)

	_, _, err := Forward(decision, ForwardPolicy{MaxResponseBytes: 100}, NewSecretBindings(map[string]string{"api_key": "broker-1"}), store, func(request OutboundRequest, _ int) (OutboundResponse, error) {
		return OutboundResponse{}, fmt.Errorf("request failed: %+v", request)
	})
	if err == nil {
		t.Fatal("expected a transport error")
	}
	if strings.Contains(err.Error(), "super-secret-value") {
		t.Fatalf("transport error leaked the raw secret: %q", err.Error())
	}
}

// Regression, found during a whole-phase audit: SecretBindings used to be a
// plain map[string]string, unlike ArtifactCache/MemoryRunJournal/
// CredentialStore, which all guard concurrent access with a mutex. Run
// concurrent Bind calls alongside concurrent resolve calls (via
// ResolveSecrets) under go test's own data-race-sensitive execution;
// without a mutex this either panics ("concurrent map read and map write")
// or, on this build (no cgo, so -race isn't available), can still corrupt
// the map's internal state. The important guarantee this test locks in is
// that SecretBindings' own exported API has no plain-map literal path left
// that could reintroduce the unsynchronized version.
func TestSecretBindingsConcurrentAccessDoesNotPanic(t *testing.T) {
	bindings := NewSecretBindings(nil)
	store := &CredentialStore{}
	store.Put("ref", "value")
	rendered := []byte(`{"method":"GET","url":"https://x.test","headers":{"Authorization":"Bearer {{ secret.k }}"},"body":null}`)

	done := make(chan struct{})
	go func() {
		defer close(done)
		for i := 0; i < 500; i++ {
			bindings.Bind("k", "ref")
		}
	}()
	for i := 0; i < 500; i++ {
		_, _, _ = ResolveSecrets(rendered, bindings, store)
	}
	<-done
}
