package proxy

import "testing"

func TestCredentialStoreDeleteIsIdempotent(t *testing.T) {
	store := &CredentialStore{}
	store.Delete("never-stored")
	store.Put("broker-1", "raw-secret")
	store.Delete("broker-1")
	store.Delete("broker-1")

	if _, ok := store.resolve("broker-1"); ok {
		t.Fatal("deleted credential still resolves")
	}
}

// CredentialStore's public API intentionally consists only of Put and Delete;
// raw values are available solely through the package-private resolution path
// used by ResolveSecrets.
