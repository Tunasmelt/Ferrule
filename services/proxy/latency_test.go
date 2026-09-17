package proxy

import (
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"sort"
	"testing"
	"time"
)

func TestProxyLatencyP95Under50RPS(t *testing.T) {
	if testing.Short() {
		t.Skip("latency assertions are unreliable when the short test suite is requested")
	}
	upstream := httptest.NewServer(http.HandlerFunc(func(writer http.ResponseWriter, _ *http.Request) {
		writer.Header().Set("Content-Type", "application/json")
		_, _ = writer.Write([]byte(`{"ok":true}`))
	}))
	defer upstream.Close()

	cache := NewArtifactCache()
	journal := NewMemoryRunJournal()
	request, err := registerProbeFixture(cache, journal, "latency", upstream.URL, http.MethodGet, nil)
	if err != nil {
		t.Fatal(err)
	}
	proxyServer := httptest.NewServer((&Server{
		Cache: cache, Journal: journal, Store: &CredentialStore{},
		Policy: ForwardPolicy{MaxResponseBytes: 1024}, Transport: NewHTTPTransport(&http.Client{}),
	}).Handler())
	defer proxyServer.Close()

	const requestCount = 150
	latencies := make([]time.Duration, 0, requestCount)
	next := time.Now()
	for range requestCount {
		now := time.Now()
		if now.Before(next) {
			time.Sleep(next.Sub(now))
		}
		started := time.Now()
		response, body, err := sendProbeRequest(proxyServer.URL, request)
		latencies = append(latencies, time.Since(started))
		if err != nil {
			t.Fatal(err)
		}
		if response.StatusCode != http.StatusOK {
			t.Fatalf("status=%d body=%s", response.StatusCode, body)
		}
		next = next.Add(20 * time.Millisecond)
	}
	sort.Slice(latencies, func(i, j int) bool { return latencies[i] < latencies[j] })
	p95 := latencies[(95*len(latencies)+99)/100-1]
	t.Logf("p95=%s over %d requests at 50 rps", p95, requestCount)
	if p95 >= 25*time.Millisecond {
		summary, _ := json.Marshal(latencies)
		t.Fatalf("p95 proxy latency %s exceeds 25ms; samples=%s", p95, summary)
	}
}
