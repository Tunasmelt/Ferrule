package proxy

import (
	"bytes"
	"fmt"
	"strings"
	"sync"
)

// SecretBindings maps a plan's secret name to a broker_ref. Supplying this
// alongside the store is the deliberate v1 scope boundary until workspace
// and binding management exist.
//
// This is a mutex-guarded struct, not a plain map, matching ArtifactCache/
// MemoryRunJournal/CredentialStore. Found missing during a whole-phase
// audit: a plain map[string]string has no such protection, and while
// nothing today mutates bindings concurrently with live traffic, a future
// credential-rebind/rotation operation running while requests are in
// flight would be a real Go data race (concurrent map read and map write
// crashes the process; it is not a benign inconsistency).
type SecretBindings struct {
	mu     sync.RWMutex
	values map[string]string
}

// NewSecretBindings returns bindings seeded from initial (nil is fine, an
// empty binding set). initial is copied, not aliased.
func NewSecretBindings(initial map[string]string) *SecretBindings {
	values := make(map[string]string, len(initial))
	for name, brokerRef := range initial {
		values[name] = brokerRef
	}
	return &SecretBindings{values: values}
}

// Bind sets (or replaces) the broker_ref a secret name resolves to.
func (b *SecretBindings) Bind(name, brokerRef string) {
	b.mu.Lock()
	defer b.mu.Unlock()
	if b.values == nil {
		b.values = make(map[string]string)
	}
	b.values[name] = brokerRef
}

func (b *SecretBindings) resolve(name string) (string, bool) {
	b.mu.RLock()
	defer b.mu.RUnlock()
	brokerRef, ok := b.values[name]
	return brokerRef, ok
}

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
func ResolveSecrets(rendered []byte, bindings *SecretBindings, store *CredentialStore) ([]byte, []string, error) {
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
		if bindings == nil {
			return nil, nil, authFailure("secret %q has no binding", name)
		}
		brokerRef, ok := bindings.resolve(name)
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
