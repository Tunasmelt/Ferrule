package proxy

import (
	"bytes"
	"sort"
)

const redactionPlaceholder = "[REDACTED]"

// Redact returns a copy with every non-empty secret value removed. Values are
// replaced longest-first so an overlapping shorter value cannot expose a
// suffix of a longer credential.
func Redact(data []byte, secretValues []string) []byte {
	values := append([]string(nil), secretValues...)
	sort.Slice(values, func(i, j int) bool { return len(values[i]) > len(values[j]) })
	redacted := append([]byte(nil), data...)
	for _, value := range values {
		if value != "" {
			redacted = bytes.ReplaceAll(redacted, []byte(value), []byte(redactionPlaceholder))
		}
	}
	return redacted
}
