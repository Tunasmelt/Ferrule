package proxy

import (
	"fmt"
	"strings"
	"testing"
)

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

// Regression, found during the 2c audit: Go's fmt package prints unexported
// fields under %v/%+v/%#v via reflection, ignoring normal field visibility.
// Without a String()/GoString() method, any accidental
// fmt.Sprintf("%+v", store) (in a log line, a test failure message, a
// future debugging statement) would dump every stored credential verbatim.
func TestCredentialStoreFormattingDoesNotLeakValues(t *testing.T) {
	store := &CredentialStore{}
	store.Put("broker-1", "super-secret-value")
	for _, verb := range []string{"%v", "%+v", "%#v", "%s"} {
		formatted := fmt.Sprintf(verb, store)
		if strings.Contains(formatted, "super-secret-value") {
			t.Fatalf("verb %s leaked the raw secret value: %s", verb, formatted)
		}
	}
}
