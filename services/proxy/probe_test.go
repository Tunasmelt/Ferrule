package proxy

import (
	"fmt"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
)

func TestPermissionProbes(t *testing.T) {
	cache := NewArtifactCache()
	journal := NewMemoryRunJournal()
	store := &CredentialStore{}
	bindings := SecretBindings{}
	policy := ForwardPolicy{
		MaxRedirects:        2,
		MaxResponseBytes:    128,
		AllowedContentTypes: []string{"application/json"},
	}
	proxyServer := httptest.NewServer((&Server{
		Cache: cache, Journal: journal, Store: store, Bindings: bindings,
		Policy: policy, Transport: NewHTTPTransport(&http.Client{}),
	}).Handler())
	defer proxyServer.Close()

	results := RunPermissionProbes(proxyServer.URL, ProbeEnvironment{
		Cache: cache, Journal: journal, Store: store, Bindings: bindings, Policy: policy,
	})
	var failures []string
	for _, result := range results {
		t.Logf("%s: passed=%t detail=%s", result.Name, result.Passed, result.Detail)
		if !result.Passed {
			failures = append(failures, fmt.Sprintf("%s: %s", result.Name, result.Detail))
		}
	}
	if len(failures) != 0 {
		t.Fatalf("permission probes failed:\n%s", strings.Join(failures, "\n"))
	}
}
