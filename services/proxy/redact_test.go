package proxy

import (
	"bytes"
	"testing"
)

func TestRedact(t *testing.T) {
	t.Run("known value", func(t *testing.T) {
		got := Redact([]byte("token=secret-value"), []string{"secret-value"})
		if string(got) != "token=[REDACTED]" {
			t.Fatalf("Redact() = %q", got)
		}
	})

	t.Run("longer value first", func(t *testing.T) {
		got := Redact([]byte("abcdef abc"), []string{"abc", "abcdef"})
		if string(got) != "[REDACTED] [REDACTED]" {
			t.Fatalf("Redact() = %q", got)
		}
	})

	t.Run("empty values", func(t *testing.T) {
		input := []byte("unchanged")
		got := Redact(input, nil)
		if !bytes.Equal(got, input) {
			t.Fatalf("Redact() = %q", got)
		}
	})

	// Regression, found during the 2c audit: a secret containing a
	// character JSON must escape (a literal quote) can be echoed back by
	// an upstream inside the upstream's OWN JSON response, where JSON
	// serialization re-escapes it (" becomes \"). A raw-value-only search
	// never matches that escaped substring.
	t.Run("JSON-escaped echo", func(t *testing.T) {
		secret := `bearer-"token"-value`
		upstreamJSON := []byte(`{"error":"invalid credential: bearer-\"token\"-value"}`)
		got := Redact(upstreamJSON, []string{secret})
		if bytes.Contains(got, []byte("token")) {
			t.Fatalf("Redact() = %q, still contains the secret in its escaped form", got)
		}
	})
}
