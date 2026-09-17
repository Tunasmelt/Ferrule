package main

import (
	"os"
	"path/filepath"
	"runtime"
	"strings"
	"testing"
)

func TestKeygenCreatesNewKeypairWithRestrictedPrivateKey(t *testing.T) {
	directory := t.TempDir()
	if err := keygen(directory); err != nil {
		t.Fatal(err)
	}
	privateInfo, err := os.Stat(filepath.Join(directory, "dev-private.pem"))
	if err != nil {
		t.Fatal(err)
	}
	publicInfo, err := os.Stat(filepath.Join(directory, "dev-public.pem"))
	if err != nil {
		t.Fatal(err)
	}
	if runtime.GOOS != "windows" {
		// Windows ACLs, not chmod-style mode bits, enforce file access.
		if got := privateInfo.Mode().Perm(); got != 0600 {
			t.Fatalf("private key mode = %o, want 600", got)
		}
		if got := publicInfo.Mode().Perm(); got != 0644 {
			t.Fatalf("public key mode = %o, want 644", got)
		}
	}
}

func TestKeygenRefusesToOverwriteExistingPrivateKey(t *testing.T) {
	directory := t.TempDir()
	privatePath := filepath.Join(directory, "dev-private.pem")
	if err := os.WriteFile(privatePath, []byte("race winner"), 0600); err != nil {
		t.Fatal(err)
	}
	err := keygen(directory)
	if err == nil || !strings.Contains(err.Error(), "refusing to overwrite") {
		t.Fatalf("keygen error = %v, want overwrite refusal", err)
	}
	contents, err := os.ReadFile(privatePath)
	if err != nil {
		t.Fatal(err)
	}
	if string(contents) != "race winner" {
		t.Fatalf("existing private key was overwritten: %q", contents)
	}
}

func TestKeygenRemovesPrivateKeyWhenPublicCreateFails(t *testing.T) {
	directory := t.TempDir()
	publicPath := filepath.Join(directory, "dev-public.pem")
	if err := os.WriteFile(publicPath, []byte("existing public key"), 0644); err != nil {
		t.Fatal(err)
	}
	err := keygen(directory)
	if err == nil || !strings.Contains(err.Error(), "refusing to overwrite") {
		t.Fatalf("keygen error = %v, want overwrite refusal", err)
	}
	if _, err := os.Stat(filepath.Join(directory, "dev-private.pem")); !os.IsNotExist(err) {
		t.Fatalf("private key remains after public-key failure: %v", err)
	}
	contents, err := os.ReadFile(publicPath)
	if err != nil {
		t.Fatal(err)
	}
	if string(contents) != "existing public key" {
		t.Fatalf("existing public key was overwritten: %q", contents)
	}
}
