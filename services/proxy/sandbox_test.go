package proxy

import (
	"encoding/json"
	"fmt"
	"net/http"
	"net/http/httptest"
	"net/url"
	"os"
	"strings"
	"sync/atomic"
	"testing"
	"time"

	artifact "ferrule/packages/artifact/go"
)

func TestSandboxVerification(t *testing.T) {
	if os.Getenv("FERRULE_SANDBOX_LIVE") == "" {
		t.Skip("set FERRULE_SANDBOX_LIVE=1 to run live sandbox verification (see gate-4a)")
	}

	cache := NewArtifactCache()
	journal := NewMemoryRunJournal()
	store := &CredentialStore{}
	bindings := NewSecretBindings(map[string]string{})
	policy := ForwardPolicy{
		MaxRedirects:        2,
		MaxResponseBytes:    1 << 20,
		AllowedContentTypes: []string{"application/json"},
	}
	const authToken = "sandbox-verification-token"
	server := httptest.NewServer((&Server{
		Cache: cache, Journal: journal, Store: store, Bindings: bindings,
		Policy: policy, AuthToken: authToken,
		Transport: NewHTTPTransport(&http.Client{Timeout: 15 * time.Second}),
	}).Handler())
	defer server.Close()

	results := RunPermissionProbes(server.URL, ProbeEnvironment{
		Cache: cache, Journal: journal, Store: store, Bindings: bindings,
		Policy: policy, AuthToken: authToken,
	})
	var probeFailures []string
	for _, result := range results {
		t.Logf("permission probe %s: passed=%t detail=%s", result.Name, result.Passed, result.Detail)
		if !result.Passed {
			probeFailures = append(probeFailures, fmt.Sprintf("%s: %s", result.Name, result.Detail))
		}
	}
	if len(probeFailures) != 0 {
		t.Fatalf("permission probes blocked sandbox verification:\n%s", strings.Join(probeFailures, "\n"))
	}

	nodes := []struct {
		name  string
		step  map[string]any
		input map[string]any
	}{
		{"pokeapi getPokemonById", sandboxStep("getPokemonById", "https://pokeapi.co/api/v2/pokemon/{{ input.id }}", nil), map[string]any{"id": "ditto"}},
		{"pokeapi listPokemon", sandboxStep("listPokemon", "https://pokeapi.co/api/v2/pokemon", map[string]any{"limit": "{{ input.limit }}", "offset": "{{ input.offset }}"}), map[string]any{"limit": 5, "offset": 0}},
		{"jsonplaceholder getUser", sandboxStep("getUser", "https://jsonplaceholder.typicode.com/users/{{ input.id }}", nil), map[string]any{"id": 1}},
		{"open-meteo getForecast", sandboxStep("getForecast", "https://api.open-meteo.com/v1/forecast", map[string]any{"latitude": "{{ input.latitude }}", "longitude": "{{ input.longitude }}"}), map[string]any{"latitude": 52.52, "longitude": 13.41}},
		// Not searchGeocoding: milestone 4a's own live run against the real
		// API caught that tests/fixtures/openapi/open-meteo.json's
		// searchGeocoding path was factually wrong (geocoding lives on
		// geocoding-api.open-meteo.com, not this fixture's top-level
		// api.open-meteo.com host -- a real bug from milestone 3a that
		// mocked testing never exercised the real endpoint to catch).
		// getElevation is confirmed correctly hosted under api.open-meteo.com.
		{"open-meteo getElevation", sandboxStep("getElevation", "https://api.open-meteo.com/v1/elevation", map[string]any{"latitude": "{{ input.latitude }}", "longitude": "{{ input.longitude }}"}), map[string]any{"latitude": 52.52, "longitude": 13.41}},
	}
	for _, node := range nodes {
		passed, detail := verifySandboxNode(t, server.URL, cache, journal, authToken, node.step, node.input)
		t.Logf("sandbox node %s: passed=%t detail=%s", node.name, passed, detail)
		if !passed {
			t.Errorf("sandbox node %s failed: %s", node.name, detail)
		}
	}

	var maliciousTargetCalls atomic.Int32
	maliciousTarget := httptest.NewServer(http.HandlerFunc(func(writer http.ResponseWriter, _ *http.Request) {
		maliciousTargetCalls.Add(1)
		writer.Header().Set("Content-Type", "application/json")
		_, _ = writer.Write([]byte(`{"pwned":true}`))
	}))
	defer maliciousTarget.Close()
	redirector := httptest.NewServer(http.HandlerFunc(func(writer http.ResponseWriter, _ *http.Request) {
		writer.Header().Set("Location", maliciousTarget.URL)
		writer.WriteHeader(http.StatusFound)
	}))
	defer redirector.Close()
	passed, detail := verifySandboxNode(t, server.URL, cache, journal, authToken, sandboxStep("maliciousRedirect", redirector.URL, nil), map[string]any{})
	t.Logf("sandbox node malicious redirect: passed=%t detail=%s", passed, detail)
	if passed {
		t.Error("malicious cross-host redirect passed sandbox verification")
	}
	if calls := maliciousTargetCalls.Load(); calls != 0 {
		t.Errorf("malicious redirect target fetched %d times", calls)
	}
}

func sandboxStep(id, rawURL string, query map[string]any) map[string]any {
	step := map[string]any{
		"id": id, "method": http.MethodGet, "url": rawURL, "headers": map[string]any{}, "pagination": "none",
		"expect": map[string]any{
			"200":     map[string]any{"route": "ok", "map": map[string]any{"body": "response"}},
			"default": map[string]any{"route": "error", "map": map[string]any{"status": "response.status"}},
		},
	}
	if query != nil {
		step["query"] = query
	}
	return step
}

var sandboxRunSequence atomic.Uint64

func verifySandboxNode(t *testing.T, baseURL string, cache *ArtifactCache, journal RunJournal, authToken string, step, input map[string]any) (bool, string) {
	t.Helper()
	inputJSON, err := json.Marshal(input)
	if err != nil {
		return false, "encode input: " + err.Error()
	}
	journalInput, err := decodeJSONMap(inputJSON)
	if err != nil {
		return false, "decode journal input: " + err.Error()
	}
	rendered, err := RenderRequest(step, journalInput, nil)
	if err != nil {
		return false, "render request: " + err.Error()
	}
	var requestURL struct {
		URL string `json:"url"`
	}
	if err := json.Unmarshal(rendered, &requestURL); err != nil {
		return false, "decode rendered request: " + err.Error()
	}
	parsed, err := url.Parse(requestURL.URL)
	if err != nil {
		return false, "parse rendered URL: " + err.Error()
	}
	plan, err := json.Marshal(map[string]any{"hosts": []string{parsed.Hostname()}, "steps": []any{step}})
	if err != nil {
		return false, "encode plan: " + err.Error()
	}
	privatePEM, publicPEM, err := artifact.GenerateDevKeypairPEM()
	if err != nil {
		return false, "generate signing key: " + err.Error()
	}
	privateKey, err := artifact.ParsePrivateKeyPEM(privatePEM)
	if err != nil {
		return false, "parse private key: " + err.Error()
	}
	publicKey, err := artifact.ParsePublicKeyPEM(publicPEM)
	if err != nil {
		return false, "parse public key: " + err.Error()
	}
	built, err := artifact.Build(plan)
	if err != nil {
		return false, "build artifact: " + err.Error()
	}
	signature, err := artifact.Sign(built, privateKey)
	if err != nil {
		return false, "sign artifact: " + err.Error()
	}
	hash := artifact.Hash(built)
	if err := cache.Push(hash, append(append([]byte(nil), built...), signature...), publicKey); err != nil {
		return false, "cache artifact: " + err.Error()
	}
	stepID, _ := step["id"].(string)
	runID := fmt.Sprintf("sandbox-%d", sandboxRunSequence.Add(1))
	entry, err := journal.RecordInput(runID, 1, hash, stepID, inputJSON, nil)
	if err != nil {
		return false, "record input: " + err.Error()
	}
	response, body, err := sendProbeRequest(baseURL, authToken, AuthorizationRequest{
		NodeVersionHash: hash, RunID: runID, StepSeq: 1, StepID: stepID,
		StepInputDigest: entry.Digest, CanonicalizedRequest: rendered,
	})
	if err != nil {
		return false, "authorize request: " + err.Error()
	}
	detail := fmt.Sprintf("status=%d body=%s", response.StatusCode, body)
	return response.StatusCode >= 200 && response.StatusCode < 300, detail
}
