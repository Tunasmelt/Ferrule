package proxy

import (
	"encoding/json"
	"errors"
	"net"
	"net/http"
	"net/http/httptest"
	"testing"
)

// Regression, found during a whole-phase audit: most Authorize/Forward
// denial paths carried this package's own Code string but no SPEC.md
// section 7 failure class at all, so a caller had no standard signal to
// route retry/alerting decisions on for most denials.
func TestSecurityEventCarriesPermissionDeniedFailureClass(t *testing.T) {
	manifest := `{"hosts":["x.test"],"steps":[{"id":"fetch","method":"GET","url":"https://x.test/42","headers":{}}]}`
	submitted := `{"method":"GET","url":"https://x.test/other","headers":{},"body":null}`
	cache, journal, request := authorizationFixture(t, manifest, submitted)
	decision := Authorize(cache, journal, request)
	if decision.ChecksPassed || decision.SecurityEvent == nil {
		t.Fatalf("expected a denial with a SecurityEvent: %+v", decision)
	}
	if decision.SecurityEvent.FailureClass != "permission_denied" {
		t.Fatalf("FailureClass = %q, want permission_denied", decision.SecurityEvent.FailureClass)
	}
}

// Regression, found the same way: a network/connectivity failure from the
// transport had no SPEC.md section 7 classification at all -- a caller
// could not distinguish "retry this" (transient/timeout) from a
// credential failure or an internal proxy fault. A timeout specifically
// must classify as "timeout", anything else from the transport as
// "transient".
func TestServerClassifiesTransportTimeoutAndTransientFailures(t *testing.T) {
	manifest := `{"hosts":["x.test"],"steps":[{"id":"fetch","method":"GET","url":"https://x.test/42","headers":{}}]}`
	submitted := `{"method":"GET","url":"https://x.test/42","headers":{},"body":null}`

	t.Run("timeout", func(t *testing.T) {
		cache, journal, request := authorizationFixture(t, manifest, submitted)
		server := httptest.NewServer((&Server{
			Cache: cache, Journal: journal, Store: &CredentialStore{}, AuthToken: testAuthToken,
			Transport: func(OutboundRequest, int) (OutboundResponse, error) {
				return OutboundResponse{}, &net.DNSError{IsTimeout: true, Err: "simulated timeout"}
			},
		}).Handler())
		defer server.Close()
		assertFailureClass(t, server.URL, request, http.StatusBadGateway, "timeout")
	})

	t.Run("transient", func(t *testing.T) {
		cache, journal, request := authorizationFixture(t, manifest, submitted)
		server := httptest.NewServer((&Server{
			Cache: cache, Journal: journal, Store: &CredentialStore{}, AuthToken: testAuthToken,
			Transport: func(OutboundRequest, int) (OutboundResponse, error) {
				return OutboundResponse{}, errors.New("connection reset by peer")
			},
		}).Handler())
		defer server.Close()
		assertFailureClass(t, server.URL, request, http.StatusBadGateway, "transient")
	})
}

func assertFailureClass(t *testing.T, baseURL string, request AuthorizationRequest, wantStatus int, wantClass string) {
	t.Helper()
	response := postAuthorization(t, baseURL, request)
	defer response.Body.Close()
	if response.StatusCode != wantStatus {
		t.Fatalf("status = %d, want %d", response.StatusCode, wantStatus)
	}
	var body struct {
		FailureClass string `json:"failure_class"`
	}
	if err := json.NewDecoder(response.Body).Decode(&body); err != nil {
		t.Fatal(err)
	}
	if body.FailureClass != wantClass {
		t.Fatalf("failure_class = %q, want %q", body.FailureClass, wantClass)
	}
}

var _ net.Error = (*net.DNSError)(nil)
