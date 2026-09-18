package proxy

import (
	"encoding/json"
	"fmt"
	"net/http"
	"net/http/httptest"
	"os"
	"sort"
	"testing"
	"time"
)

// This is a real wall-clock timing assertion, not a determinism check --
// flaky on a loaded or shared machine through no fault of the proxy code
// (GC pauses, scheduler contention, a busy CI runner). gate-2a, gate-2b,
// and gate-2c all run the unfiltered `go test ./services/proxy/...` (there
// is no per-milestone test binary split), so if this ran by default it
// would silently make an unrelated milestone's gate fail on timing noise.
// Opt-in via FERRULE_LATENCY_BENCHMARK, set only by gate-2d, keeps this
// contained to the one gate that's actually about latency.
func TestProxyLatencyP95Under50RPS(t *testing.T) {
	if os.Getenv("FERRULE_LATENCY_BENCHMARK") == "" {
		t.Skip("set FERRULE_LATENCY_BENCHMARK=1 to run this timing-sensitive benchmark (see gate-2d)")
	}
	upstream := httptest.NewServer(http.HandlerFunc(func(writer http.ResponseWriter, _ *http.Request) {
		writer.Header().Set("Content-Type", "application/json")
		_, _ = writer.Write([]byte(`{"ok":true}`))
	}))
	defer upstream.Close()

	cache := NewArtifactCache()
	journal := NewMemoryRunJournal()
	proxyServer := httptest.NewServer((&Server{
		Cache: cache, Journal: journal, Store: &CredentialStore{}, AuthToken: testAuthToken,
		Policy: ForwardPolicy{MaxResponseBytes: 1024}, Transport: NewHTTPTransport(&http.Client{}),
	}).Handler())
	defer proxyServer.Close()

	const requestCount = 150
	// Replay protection (found during the whole-phase audit) denies a
	// second authorization of the same (run_id, step_seq) once it has
	// completed once, so this benchmark needs its own fresh journal entry
	// per request -- exactly as 150 independent workflow runs would have --
	// not the same request resent 150 times. Pre-register all of them
	// outside the timed loop so artifact signing/journaling overhead
	// (irrelevant to what this benchmark measures) doesn't pollute the
	// per-request latency samples.
	requests := make([]AuthorizationRequest, requestCount)
	for i := range requests {
		request, err := registerProbeFixture(cache, journal, fmt.Sprintf("latency-%d", i), upstream.URL, http.MethodGet, nil)
		if err != nil {
			t.Fatal(err)
		}
		requests[i] = request
	}

	latencies := make([]time.Duration, 0, requestCount)
	next := time.Now()
	for _, request := range requests {
		now := time.Now()
		if now.Before(next) {
			time.Sleep(next.Sub(now))
		}
		started := time.Now()
		response, body, err := sendProbeRequest(proxyServer.URL, testAuthToken, request)
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
