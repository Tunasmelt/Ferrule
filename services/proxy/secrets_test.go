package proxy

import (
	"bytes"
	"errors"
	"testing"
)

func TestResolveSecretsFailsWithAuthAfterCredentialDeletion(t *testing.T) {
	store := &CredentialStore{}
	store.Put("broker-1", "token-value")
	rendered := []byte(`{"method":"GET","url":"https://api.example.com","headers":{"Authorization":"Bearer {{ secret.acme_erp_api_key }}"},"body":null}`)
	bindings := SecretBindings{"acme_erp_api_key": "broker-1"}

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
	bindings := SecretBindings{"token": "broker-1"}
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
	_, _, err := Forward(decision, ForwardPolicy{MaxResponseBytes: 100}, SecretBindings{"acme_erp_api_key": "broker-1"}, store, func(request OutboundRequest, _ int) (OutboundResponse, error) {
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

	response, _, err := Forward(decision, ForwardPolicy{MaxResponseBytes: 100}, SecretBindings{"api_key": "broker-1"}, store, func(_ OutboundRequest, _ int) (OutboundResponse, error) {
		return OutboundResponse{Status: 401, Headers: map[string]string{"X-Echo": "Bearer super-secret"}, Body: []byte("rejected super-secret")}, nil
	})
	if err != nil {
		t.Fatal(err)
	}
	if bytes.Contains(response.Body, []byte("super-secret")) || response.Headers["X-Echo"] != "Bearer [REDACTED]" {
		t.Fatalf("response was not redacted: %+v", response)
	}
}
