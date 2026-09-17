package proxy

import (
	"bytes"
	"crypto/ed25519"
	"encoding/json"
	"errors"
	"sync"

	artifact "ferrule/packages/artifact/go"
)

// ArtifactCache accepts dispatch-time pushes through its Go API only. The wire
// framing is canonical artifact bytes followed by a 64-byte Ed25519 signature.
type ArtifactCache struct {
	mu        sync.RWMutex
	manifests map[string][]byte
}

func NewArtifactCache() *ArtifactCache {
	return &ArtifactCache{manifests: make(map[string][]byte)}
}

func (cache *ArtifactCache) Push(hash string, signedArtifactBytes []byte, publicKey ed25519.PublicKey) error {
	if len(signedArtifactBytes) < ed25519.SignatureSize {
		return errors.New("signed artifact is truncated")
	}
	cut := len(signedArtifactBytes) - ed25519.SignatureSize
	payload, signature := signedArtifactBytes[:cut], signedArtifactBytes[cut:]
	if artifact.Hash(payload) != hash || !artifact.Verify(payload, signature, publicKey) {
		return errors.New("artifact verification failed")
	}
	canonical, err := artifact.Canonicalize(payload)
	if err != nil {
		return err
	}
	if _, err := decodeJSONMap(canonical); err != nil {
		return err
	}
	cache.mu.Lock()
	defer cache.mu.Unlock()
	if _, exists := cache.manifests[hash]; exists {
		return errors.New("artifact already cached")
	}
	cache.manifests[hash] = append([]byte(nil), canonical...)
	return nil
}

func (cache *ArtifactCache) Get(hash string) (map[string]any, bool) {
	cache.mu.RLock()
	data, ok := cache.manifests[hash]
	data = append([]byte(nil), data...)
	cache.mu.RUnlock()
	if !ok {
		return nil, false
	}
	manifest, err := decodeJSONMap(data)
	if err != nil {
		return nil, false
	}
	return manifest, true
}

func decodeJSONMap(data []byte) (map[string]any, error) {
	var value map[string]any
	decoder := json.NewDecoder(bytes.NewReader(data))
	decoder.UseNumber()
	err := decoder.Decode(&value)
	return value, err
}
