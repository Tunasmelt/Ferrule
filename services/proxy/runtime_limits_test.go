package proxy

import (
	"net/http"
	"net/http/httptest"
	"reflect"
	"testing"
)

func TestMergeForwardPolicyTakesMoreRestrictiveValues(t *testing.T) {
	server := ForwardPolicy{MaxRedirects: 5, MaxResponseBytes: 10000, AllowedContentTypes: []string{"application/json", "text/plain"}}

	t.Run("nil artifact limits returns server policy unchanged", func(t *testing.T) {
		merged := MergeForwardPolicy(server, nil)
		if !reflect.DeepEqual(merged, server) {
			t.Fatalf("merged = %+v, want unchanged %+v", merged, server)
		}
	})

	t.Run("artifact tightens numeric limits", func(t *testing.T) {
		artifact := &ForwardPolicy{MaxRedirects: 1, MaxResponseBytes: 10}
		merged := MergeForwardPolicy(server, artifact)
		if merged.MaxRedirects != 1 || merged.MaxResponseBytes != 10 {
			t.Fatalf("merged = %+v, want the artifact's tighter values", merged)
		}
	})

	t.Run("artifact cannot widen numeric limits", func(t *testing.T) {
		artifact := &ForwardPolicy{MaxRedirects: 100, MaxResponseBytes: 999999}
		merged := MergeForwardPolicy(server, artifact)
		if merged.MaxRedirects != server.MaxRedirects || merged.MaxResponseBytes != server.MaxResponseBytes {
			t.Fatalf("merged = %+v, want server's tighter values preserved", merged)
		}
	})

	t.Run("content types intersect", func(t *testing.T) {
		artifact := &ForwardPolicy{AllowedContentTypes: []string{"text/plain", "application/xml"}}
		merged := MergeForwardPolicy(server, artifact)
		if len(merged.AllowedContentTypes) != 1 || merged.AllowedContentTypes[0] != "text/plain" {
			t.Fatalf("merged content types = %v, want just [text/plain]", merged.AllowedContentTypes)
		}
	})
}

// Regression, found during a whole-phase audit: ForwardPolicy used to be a
// single process-wide value the caller supplied, with nothing read from
// the signed artifact at all -- two artifacts with different declared
// limits got the identical effective policy, and a server configured more
// permissively than a specific artifact's own limits silently widened that
// artifact's authority. This drives a real HTTP round trip where the
// SERVER is configured generously (10000 bytes) but the ARTIFACT declares
// a much smaller runtime_limits.max_output_bytes (10), and confirms the
// artifact's tighter limit is the one actually enforced.
func TestServerEnforcesArtifactRuntimeLimitsOverServerPolicy(t *testing.T) {
	manifest := `{"hosts":["x.test"],"steps":[{"id":"fetch","method":"GET","url":"https://x.test/42","headers":{}}],"runtime_limits":{"max_redirects":0,"max_output_bytes":10}}`
	submitted := `{"method":"GET","url":"https://x.test/42","headers":{},"body":null}`
	cache, journal, request := authorizationFixture(t, manifest, submitted)

	server := httptest.NewServer((&Server{
		Cache: cache, Journal: journal, Store: &CredentialStore{}, AuthToken: testAuthToken,
		Policy: ForwardPolicy{MaxRedirects: 5, MaxResponseBytes: 10000}, // server alone would allow this response
		Transport: func(OutboundRequest, int) (OutboundResponse, error) {
			return OutboundResponse{Status: http.StatusOK, Body: []byte("this response is more than ten bytes long")}, nil
		},
	}).Handler())
	defer server.Close()

	response := postAuthorization(t, server.URL, request)
	defer response.Body.Close()
	if response.StatusCode != http.StatusBadGateway {
		t.Fatalf("status = %d, want 502 (denied by the artifact's own tighter runtime_limits)", response.StatusCode)
	}
}
