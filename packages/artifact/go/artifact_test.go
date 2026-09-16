package artifact

import (
	"crypto/ed25519"
	"crypto/rand"
	"os"
	"path/filepath"
	"sort"
	"strings"
	"testing"
)

func fixtureArtifacts(t *testing.T) [][]byte {
	t.Helper()
	paths, err := filepath.Glob(filepath.Join("..", "..", "..", "tests", "fixtures", "canonical", "*.json"))
	if err != nil {
		t.Fatal(err)
	}
	sort.Strings(paths)
	if len(paths) != 20 {
		t.Fatalf("got %d fixtures, want 20", len(paths))
	}
	artifacts := make([][]byte, 0, len(paths))
	for _, path := range paths {
		raw, err := os.ReadFile(path)
		if err != nil {
			t.Fatal(err)
		}
		built, err := Build(raw)
		if err != nil {
			t.Fatalf("Build(%s): %v", path, err)
		}
		artifacts = append(artifacts, built)
	}
	return artifacts
}

func TestAllFixturesBuildSignVerify(t *testing.T) {
	publicKey, privateKey, err := ed25519.GenerateKey(rand.Reader)
	if err != nil {
		t.Fatal(err)
	}
	for index, artifact := range fixtureArtifacts(t) {
		signature, err := Sign(artifact, privateKey)
		if err != nil {
			t.Fatal(err)
		}
		if !Verify(artifact, signature, publicKey) {
			t.Errorf("fixture %d did not verify", index)
		}
		if !strings.HasPrefix(Hash(artifact), "sha256:") {
			t.Errorf("fixture %d hash has wrong prefix", index)
		}
	}
}

func TestMutationAndCrossArtifactReuseFail(t *testing.T) {
	publicKey, privateKey, err := ed25519.GenerateKey(rand.Reader)
	if err != nil {
		t.Fatal(err)
	}
	artifacts := fixtureArtifacts(t)
	signature, err := Sign(artifacts[12], privateKey)
	if err != nil {
		t.Fatal(err)
	}
	for index := range artifacts[12] {
		mutated := append([]byte(nil), artifacts[12]...)
		mutated[index] ^= 1
		if Verify(mutated, signature, publicKey) {
			t.Errorf("artifact verified after mutation at byte %d", index)
		}
	}
	if Verify(artifacts[13], signature, publicKey) {
		t.Error("signature verified against a different artifact")
	}
}

func TestMalformedSignaturesFailClosed(t *testing.T) {
	publicKey, privateKey, err := ed25519.GenerateKey(rand.Reader)
	if err != nil {
		t.Fatal(err)
	}
	artifact := fixtureArtifacts(t)[0]
	signature, err := Sign(artifact, privateKey)
	if err != nil {
		t.Fatal(err)
	}
	for _, malformed := range [][]byte{nil, signature[:63], append(signature, 0), make([]byte, 64)} {
		if Verify(artifact, malformed, publicKey) {
			t.Errorf("signature length %d verified", len(malformed))
		}
	}
	if Verify(artifact, signature, []byte("wrong-length key")) {
		t.Error("wrong-length public key verified")
	}
}
