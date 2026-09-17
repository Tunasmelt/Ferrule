package proxy

import (
	"io"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
)

func TestHTTPTransportRoundTripsResponse(t *testing.T) {
	upstream := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.Method != http.MethodPost {
			t.Errorf("method = %q", r.Method)
		}
		body, err := io.ReadAll(r.Body)
		if err != nil || string(body) != "request body" {
			t.Errorf("body = %q, error = %v", body, err)
		}
		w.Header().Add("X-Value", "one")
		w.Header().Add("X-Value", "two")
		w.WriteHeader(http.StatusCreated)
		_, _ = w.Write([]byte("response body"))
	}))
	defer upstream.Close()

	transport := NewHTTPTransport(nil)
	response, err := transport(OutboundRequest{
		Method: http.MethodPost, URL: upstream.URL,
		Headers: map[string]string{"Content-Type": "text/plain"}, Body: []byte("request body"),
	}, 100)
	if err != nil {
		t.Fatal(err)
	}
	if response.Status != http.StatusCreated || response.Headers["X-Value"] != "one, two" || string(response.Body) != "response body" {
		t.Fatalf("response = %+v", response)
	}
}

func TestHTTPTransportReturnsRedirectWithoutFollowing(t *testing.T) {
	var followed bool
	upstream := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path == "/target" {
			followed = true
			w.WriteHeader(http.StatusOK)
			return
		}
		http.Redirect(w, r, "/target", http.StatusFound)
	}))
	defer upstream.Close()

	response, err := NewHTTPTransport(http.DefaultClient)(OutboundRequest{Method: http.MethodGet, URL: upstream.URL}, 100)
	if err != nil {
		t.Fatal(err)
	}
	if response.Status != http.StatusFound || response.Headers["Location"] != "/target" || followed {
		t.Fatalf("redirect was followed: response=%+v followed=%v", response, followed)
	}
}

func TestHTTPTransportRejectsOversizedResponse(t *testing.T) {
	upstream := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		_, _ = w.Write([]byte(strings.Repeat("x", 11)))
	}))
	defer upstream.Close()

	_, err := NewHTTPTransport(nil)(OutboundRequest{Method: http.MethodGet, URL: upstream.URL}, 10)
	if err == nil || !strings.Contains(err.Error(), "exceeds 10 byte limit") {
		t.Fatalf("error = %v", err)
	}
}
