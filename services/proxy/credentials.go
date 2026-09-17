package proxy

import "sync"

// CredentialStore is the deliberately in-memory credential store for v1.
// Persistence and workspace credential management do not exist yet; raw
// values live only inside the proxy process and are addressed by broker_ref.
type CredentialStore struct {
	mu     sync.RWMutex
	values map[string]string
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
