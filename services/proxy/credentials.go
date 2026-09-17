package proxy

import (
	"fmt"
	"sync"
)

// CredentialStore is the deliberately in-memory credential store for v1.
// Persistence and workspace credential management do not exist yet; raw
// values live only inside the proxy process and are addressed by broker_ref.
type CredentialStore struct {
	mu     sync.RWMutex
	values map[string]string
}

// String and GoString exist so an accidental fmt.Sprintf("%v", store) /
// "%+v" / "%#v" / log line elsewhere in this codebase (or a future one)
// can never dump raw secret values through Go's reflection-based default
// struct formatting, which does not respect field visibility the way
// normal Go code access does. Without these, %+v and %#v would print
// every stored credential verbatim regardless of the unexported `values`
// field -- confirmed by reproduction during the 2c audit.
func (s *CredentialStore) String() string {
	s.mu.RLock()
	defer s.mu.RUnlock()
	return fmt.Sprintf("CredentialStore{%d credentials}", len(s.values))
}

func (s *CredentialStore) GoString() string {
	return s.String()
}

func (s *CredentialStore) Put(brokerRef, value string) {
	s.mu.Lock()
	defer s.mu.Unlock()
	if s.values == nil {
		s.values = make(map[string]string)
	}
	s.values[brokerRef] = value
}

func (s *CredentialStore) Delete(brokerRef string) {
	s.mu.Lock()
	defer s.mu.Unlock()
	delete(s.values, brokerRef)
}

func (s *CredentialStore) resolve(brokerRef string) (string, bool) {
	s.mu.RLock()
	defer s.mu.RUnlock()
	value, ok := s.values[brokerRef]
	return value, ok
}
