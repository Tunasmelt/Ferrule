package proxy

import (
	"bytes"
	"fmt"
	"strings"
)

// SecretBindings maps a plan's secret name to a broker_ref. Supplying this
// map with the store is the deliberate v1 scope boundary until workspace and
// binding management exist.
type SecretBindings map[string]string

// FailureClassError carries a SPEC.md failure class without requiring callers
// to inspect human-readable error text.
type FailureClassError struct {
	Class string
	Err   error
}

func (e *FailureClassError) Error() string { return e.Err.Error() }
func (e *FailureClassError) Unwrap() error { return e.Err }

// ResolveSecrets substitutes secret markers in the canonical JSON envelope
// before decodeOutboundRequest. Working on a copy of the envelope covers the
// method, URL, headers, and body uniformly without mutating the authorized
// Decision.RenderedRequest. The returned values are the literal credentials
// substituted and must be passed to Redact before exposing response data.
func ResolveSecrets(rendered []byte, bindings SecretBindings, store *CredentialStore) ([]byte, []string, error) {
	resolved := append([]byte(nil), rendered...)
	replacements := make(map[string]string)
	values := make([]string, 0)
	seenValues := make(map[string]struct{})

	for _, match := range marker.FindAllSubmatch(rendered, -1) {
		path := string(match[1])
		if !strings.HasPrefix(path, "secret.") {
			continue
		}
		name := strings.TrimPrefix(path, "secret.")
		brokerRef, ok := bindings[name]
		if !ok {
			return nil, nil, authFailure("secret %q has no binding", name)
		}
		if store == nil {
			return nil, nil, authFailure("secret %q has no credential store", name)
		}
		value, ok := store.resolve(brokerRef)
		if !ok {
			return nil, nil, authFailure("credential %q bound to secret %q is missing", brokerRef, name)
		}
		// Escape for embedding inside the JSON string this marker already
		// sits within -- reuse render.go's own JSON string escaping
		// (writePythonString) rather than strconv.Quote, which is Go string
		// syntax, not JSON: it emits \a, \v, and \xHH for certain control
		// bytes, none of which are valid JSON escapes. A credential value
		// containing one of those bytes would otherwise silently produce a
		// malformed request that fails to decode instead of being sent.
		var buffer bytes.Buffer
		writePythonString(&buffer, value)
		quoted := buffer.String()
		replacements[string(match[0])] = quoted[1 : len(quoted)-1]
		if _, seen := seenValues[value]; !seen {
			seenValues[value] = struct{}{}
			values = append(values, value)
		}
	}

	resolved = marker.ReplaceAllFunc(resolved, func(match []byte) []byte {
		if replacement, ok := replacements[string(match)]; ok {
			return []byte(replacement)
		}
		return match
	})
	return resolved, values, nil
}

func authFailure(format string, args ...any) error {
	return &FailureClassError{Class: "auth", Err: fmt.Errorf(format, args...)}
}
