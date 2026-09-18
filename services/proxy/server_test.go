package proxy

import (
	"bytes"
	"encoding/json"
	"io"
	"net/http"
	"net/http/httptest"
	"sync/atomic"
	"testing"
)

// testAuthToken is the shared secret every test server in this file is
// configured with; postAuthorization and authorizedRequest attach it as a
// Bearer token so these tests exercise the same authenticated path a real
// caller must use.
const testAuthToken = "test-shared-secret"

func TestServerAuthorizesAndForwardsOverHTTP(t *testing.T) {
	manifest := `{"hosts":["x.test"],"steps":[{"id":"fetch","method":"GET","url":"https://x.test/{{ input.id }}","headers":{}}]}`
	submitted := `{"method":"GET","url":"https://x.test/42","headers":{},"body":null}`
	cache, journal, request := authorizationFixture(t, manifest, submitted)
	var calls atomic.Int32
	server := httptest.NewServer((&Server{
		Cache: cache, Journal: journal,
		Policy:    ForwardPolicy{MaxResponseBytes: 100},
		Store:     &CredentialStore{},
		AuthToken: testAuthToken,
		Transport: func(got OutboundRequest, limit int) (OutboundResponse, error) {
			calls.Add(1)
			if got.URL != "https://x.test/42" || limit != 100 {
				t.Errorf("transport request = %+v, limit = %d", got, limit)
			}
			return OutboundResponse{Status: http.StatusOK, Headers: map[string]string{"Content-Type": "application/json"}, Body: []byte(`{"ok":true}`)}, nil
		},
	}).Handler())
	defer server.Close()

	response := postAuthorization(t, server.URL, request)
	defer response.Body.Close()
	body, err := io.ReadAll(response.Body)
	if err != nil {
		t.Fatal(err)
	}
	if response.StatusCode != http.StatusOK || response.Header.Get("Content-Type") != "application/json" || string(body) != `{"ok":true}` || calls.Load() != 1 {
		t.Fatalf("status=%d headers=%v body=%s calls=%d", response.StatusCode, response.Header, body, calls.Load())
	}
}

// Regression, found during a whole-phase audit: POST /v1/authorize had no
// authentication of its caller at all. Confirm a request with no
// Authorization header, one with a wrong token, and a Server with no
// AuthToken configured (fails closed, not "auth disabled") are all
// rejected with 401, and the transport is never invoked for any of them.
func TestServerRequiresAuthentication(t *testing.T) {
	manifest := `{"hosts":["x.test"],"steps":[{"id":"fetch","method":"GET","url":"https://x.test/42","headers":{}}]}`
	submitted := `{"method":"GET","url":"https://x.test/42","headers":{},"body":null}`

	t.Run("missing header", func(t *testing.T) {
		cache, journal, request := authorizationFixture(t, manifest, submitted)
		var calls atomic.Int32
		server := httptest.NewServer((&Server{
			Cache: cache, Journal: journal, Store: &CredentialStore{}, AuthToken: testAuthToken,
			Transport: func(OutboundRequest, int) (OutboundResponse, error) { calls.Add(1); return OutboundResponse{}, nil },
		}).Handler())
		defer server.Close()
		body, _ := json.Marshal(map[string]any{"node_version_hash": request.NodeVersionHash, "run_id": request.RunID, "step_seq": request.StepSeq, "step_id": request.StepID, "step_input_digest": request.StepInputDigest, "canonicalized_request": request.CanonicalizedRequest})
		response, err := http.Post(server.URL+authorizationPath, "application/json", bytes.NewReader(body))
		if err != nil {
			t.Fatal(err)
		}
		response.Body.Close()
		if response.StatusCode != http.StatusUnauthorized || calls.Load() != 0 {
			t.Fatalf("status=%d calls=%d", response.StatusCode, calls.Load())
		}
	})

	t.Run("wrong token", func(t *testing.T) {
		cache, journal, request := authorizationFixture(t, manifest, submitted)
		server := httptest.NewServer((&Server{
			Cache: cache, Journal: journal, Store: &CredentialStore{}, AuthToken: testAuthToken,
			Transport: func(OutboundRequest, int) (OutboundResponse, error) { return OutboundResponse{}, nil },
		}).Handler())
		defer server.Close()
		req := authorizedRequest(t, server.URL, request, "wrong-token")
		response, err := http.DefaultClient.Do(req)
		if err != nil {
			t.Fatal(err)
		}
		response.Body.Close()
		if response.StatusCode != http.StatusUnauthorized {
			t.Fatalf("status=%d", response.StatusCode)
		}
	})

	t.Run("server has no token configured", func(t *testing.T) {
		cache, journal, request := authorizationFixture(t, manifest, submitted)
		server := httptest.NewServer((&Server{
			Cache: cache, Journal: journal, Store: &CredentialStore{},
			Transport: func(OutboundRequest, int) (OutboundResponse, error) { return OutboundResponse{}, nil },
		}).Handler())
		defer server.Close()
		// Even presenting an empty token must not match an unset AuthToken.
		req := authorizedRequest(t, server.URL, request, "")
		response, err := http.DefaultClient.Do(req)
		if err != nil {
			t.Fatal(err)
		}
		response.Body.Close()
		if response.StatusCode != http.StatusUnauthorized {
			t.Fatalf("status=%d, want 401 (fail closed with no token configured)", response.StatusCode)
		}
	})
}

// Regression, closed during a whole-phase audit: authorization used to be
// fully replayable -- resubmitting an already-accepted, already-forwarded
// request re-executed the upstream side effect indefinitely. Confirm a
// second submission of the exact same request is denied with
// replay_denied, and the transport is not invoked a second time.
func TestServerDeniesReplayOfCompletedRequest(t *testing.T) {
	manifest := `{"hosts":["x.test"],"steps":[{"id":"fetch","method":"GET","url":"https://x.test/42","headers":{}}]}`
	submitted := `{"method":"GET","url":"https://x.test/42","headers":{},"body":null}`
	cache, journal, request := authorizationFixture(t, manifest, submitted)
	var calls atomic.Int32
	server := httptest.NewServer((&Server{
		Cache: cache, Journal: journal, Store: &CredentialStore{}, AuthToken: testAuthToken,
		Policy: ForwardPolicy{MaxResponseBytes: 100},
		Transport: func(OutboundRequest, int) (OutboundResponse, error) {
			calls.Add(1)
			return OutboundResponse{Status: http.StatusOK, Body: []byte("ok")}, nil
		},
	}).Handler())
	defer server.Close()

	first := postAuthorization(t, server.URL, request)
	first.Body.Close()
	if first.StatusCode != http.StatusOK {
		t.Fatalf("first request status = %d", first.StatusCode)
	}

	second := postAuthorization(t, server.URL, request)
	body, _ := io.ReadAll(second.Body)
	second.Body.Close()
	if second.StatusCode != http.StatusForbidden || !bytes.Contains(body, []byte("replay_denied")) {
		t.Fatalf("replay status=%d body=%s", second.StatusCode, body)
	}
	if calls.Load() != 1 {
		t.Fatalf("transport called %d times, want exactly 1", calls.Load())
	}
}

// Regression, found during 2d's independent review: Forward's redaction can
// change response.Body's length relative to what the upstream declared in
// its own Content-Length header (a secret and "[REDACTED]" are rarely the
// same length). Server used to copy that header through unchanged.
// Reproduced directly, in isolation from this codebase, that writing a body
// whose real length differs from a copied, now-stale Content-Length makes
// Go's own net/http client read zero bytes for the ENTIRE response and
// report "unexpected EOF" -- not a graceful truncation. This test drives a
// real HTTP round trip through a real net/http.Client against httptest, the
// same way a real worker would see it, and would have failed with
// "unexpected EOF" before the fix.
func TestServerOmitsStaleContentLengthAfterRedaction(t *testing.T) {
	manifest := `{"hosts":["x.test"],"steps":[{"id":"fetch","method":"GET","url":"https://x.test/items","headers":{"Authorization":"Bearer {{ secret.k }}"}}]}`
	submitted := `{"method":"GET","url":"https://x.test/items","headers":{"Authorization":"Bearer {{ secret.k }}"},"body":null}`
	cache, journal, request := authorizationFixture(t, manifest, submitted)
	store := &CredentialStore{}
	store.Put("ref", "ab") // shorter than the "[REDACTED]" placeholder that replaces it

	server := httptest.NewServer((&Server{
		Cache: cache, Journal: journal,
		Policy:    ForwardPolicy{MaxResponseBytes: 1000},
		Bindings:  NewSecretBindings(map[string]string{"k": "ref"}),
		Store:     store,
		AuthToken: testAuthToken,
		Transport: func(OutboundRequest, int) (OutboundResponse, error) {
			original := []byte("secret is ab here") // 18 bytes, matches the stale Content-Length below
			return OutboundResponse{
				Status:  http.StatusOK,
				Headers: map[string]string{"Content-Length": "18"},
				Body:    original,
			}, nil
		},
	}).Handler())
	defer server.Close()

	response := postAuthorization(t, server.URL, request)
	defer response.Body.Close()
	body, err := io.ReadAll(response.Body)
	if err != nil {
		t.Fatalf("client could not read the response body: %v (this is exactly the stale-Content-Length failure mode)", err)
	}
	want := "secret is [REDACTED] here"
	if string(body) != want {
		t.Fatalf("body = %q, want %q", body, want)
	}
}

func TestServerDeniesUnknownArtifactWithoutForwarding(t *testing.T) {
	var calls atomic.Int32
	server := httptest.NewServer((&Server{
		Cache: NewArtifactCache(), Journal: NewMemoryRunJournal(), Store: &CredentialStore{}, AuthToken: testAuthToken,
		Transport: func(OutboundRequest, int) (OutboundResponse, error) {
			calls.Add(1)
			return OutboundResponse{}, nil
		},
	}).Handler())
	defer server.Close()

	response := postAuthorization(t, server.URL, AuthorizationRequest{
		NodeVersionHash: "sha256:missing", RunID: "run-1", StepSeq: 1, StepID: "fetch",
		StepInputDigest: "sha256:digest", CanonicalizedRequest: json.RawMessage(`{"method":"GET"}`),
	})
	defer response.Body.Close()
	body, err := io.ReadAll(response.Body)
	if err != nil {
		t.Fatal(err)
	}
	if response.StatusCode != http.StatusForbidden || !bytes.Contains(body, []byte("artifact not found")) || calls.Load() != 0 {
		t.Fatalf("status=%d body=%s calls=%d", response.StatusCode, body, calls.Load())
	}
}

func TestServerRejectsMalformedJSONOverHTTP(t *testing.T) {
	server := httptest.NewServer((&Server{Cache: NewArtifactCache(), Journal: NewMemoryRunJournal(), AuthToken: testAuthToken}).Handler())
	defer server.Close()

	req, err := http.NewRequest(http.MethodPost, server.URL+authorizationPath, bytes.NewBufferString(`{"run_id":`))
	if err != nil {
		t.Fatal(err)
	}
	req.Header.Set("Content-Type", "application/json")
	req.Header.Set("Authorization", "Bearer "+testAuthToken)
	response, err := http.DefaultClient.Do(req)
	if err != nil {
		t.Fatal(err)
	}
	defer response.Body.Close()
	if response.StatusCode < 400 || response.StatusCode >= 500 {
		t.Fatalf("status = %d", response.StatusCode)
	}
}

func TestServerRejectsWrongMethodAndMissingFieldsOverHTTP(t *testing.T) {
	server := httptest.NewServer((&Server{Cache: NewArtifactCache(), Journal: NewMemoryRunJournal(), AuthToken: testAuthToken}).Handler())
	defer server.Close()

	response, err := http.Get(server.URL + authorizationPath)
	if err != nil {
		t.Fatal(err)
	}
	response.Body.Close()
	if response.StatusCode != http.StatusMethodNotAllowed {
		t.Fatalf("GET status = %d", response.StatusCode)
	}

	req, err := http.NewRequest(http.MethodPost, server.URL+authorizationPath, bytes.NewBufferString(`{}`))
	if err != nil {
		t.Fatal(err)
	}
	req.Header.Set("Content-Type", "application/json")
	req.Header.Set("Authorization", "Bearer "+testAuthToken)
	response, err = http.DefaultClient.Do(req)
	if err != nil {
		t.Fatal(err)
	}
	response.Body.Close()
	if response.StatusCode != http.StatusBadRequest {
		t.Fatalf("missing fields status = %d", response.StatusCode)
	}
}

func postAuthorization(t *testing.T, baseURL string, request AuthorizationRequest) *http.Response {
	t.Helper()
	req := authorizedRequest(t, baseURL, request, testAuthToken)
	response, err := http.DefaultClient.Do(req)
	if err != nil {
		t.Fatal(err)
	}
	return response
}

func authorizedRequest(t *testing.T, baseURL string, request AuthorizationRequest, token string) *http.Request {
	t.Helper()
	body, err := json.Marshal(map[string]any{
		"node_version_hash":     request.NodeVersionHash,
		"run_id":                request.RunID,
		"step_seq":              request.StepSeq,
		"step_id":               request.StepID,
		"step_input_digest":     request.StepInputDigest,
		"canonicalized_request": request.CanonicalizedRequest,
	})
	if err != nil {
		t.Fatal(err)
	}
	req, err := http.NewRequest(http.MethodPost, baseURL+authorizationPath, bytes.NewReader(body))
	if err != nil {
		t.Fatal(err)
	}
	req.Header.Set("Content-Type", "application/json")
	req.Header.Set("Authorization", "Bearer "+token)
	return req
}

// Regression, found during a whole-phase audit: decodeAuthorizationRequest
// used an unbounded json.Decoder directly on the request body, letting an
// unauthenticated network client send an arbitrarily large body before the
// JSON decode ever fails. Confirm oversized bodies are now rejected without
// the server reading the whole thing into memory first.
func TestServerRejectsOversizedRequestBodyOverHTTP(t *testing.T) {
	server := httptest.NewServer((&Server{Cache: NewArtifactCache(), Journal: NewMemoryRunJournal(), AuthToken: testAuthToken}).Handler())
	defer server.Close()

	oversized := bytes.NewReader(append([]byte(`{"run_id":"`), bytes.Repeat([]byte("x"), maxAuthorizationRequestBytes+1)...))
	req, err := http.NewRequest(http.MethodPost, server.URL+authorizationPath, oversized)
	if err != nil {
		t.Fatal(err)
	}
	req.Header.Set("Content-Type", "application/json")
	req.Header.Set("Authorization", "Bearer "+testAuthToken)
	response, err := http.DefaultClient.Do(req)
	if err != nil {
		t.Fatal(err)
	}
	defer response.Body.Close()
	if response.StatusCode < 400 || response.StatusCode >= 500 {
		t.Fatalf("status = %d, want 4xx", response.StatusCode)
	}
}
