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
}
