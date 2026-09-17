package main

import (
	"encoding/base64"
	"flag"
	"fmt"
	"io"
	"os"
	"path/filepath"

	artifact "ferrule/packages/artifact/go"
)

func fail(err error) {
	fmt.Fprintln(os.Stderr, err)
	os.Exit(1)
}

func input(path string) ([]byte, error) {
	if path == "" || path == "-" {
		return io.ReadAll(os.Stdin)
	}
	return os.ReadFile(path)
}

func writeExclusive(path string, contents []byte, mode os.FileMode) error {
	file, err := os.OpenFile(path, os.O_CREATE|os.O_EXCL|os.O_WRONLY, mode)
	if err != nil {
		return err
	}
	if _, err := file.Write(contents); err != nil {
		_ = file.Close()
		_ = os.Remove(path)
		return err
	}
	if err := file.Close(); err != nil {
		_ = os.Remove(path)
		return err
	}
	return nil
}

func keygen(directory string) error {
	privatePEM, publicPEM, err := artifact.GenerateDevKeypairPEM()
	if err != nil {
		return err
	}
	if err := os.MkdirAll(directory, 0700); err != nil {
		return err
	}
	privatePath := filepath.Join(directory, "dev-private.pem")
	publicPath := filepath.Join(directory, "dev-public.pem")
	if err := writeExclusive(privatePath, privatePEM, 0600); err != nil {
		if os.IsExist(err) {
			return fmt.Errorf("refusing to overwrite %s", privatePath)
		}
		return err
	}
	if err := writeExclusive(publicPath, publicPEM, 0644); err != nil {
		if cleanupErr := os.Remove(privatePath); cleanupErr != nil {
			return fmt.Errorf("%v; private key remains at %s: %v", err, privatePath, cleanupErr)
		}
		if os.IsExist(err) {
			return fmt.Errorf("refusing to overwrite %s", publicPath)
		}
		return err
	}
	return nil
}

func main() {
	if len(os.Args) < 2 {
		fail(fmt.Errorf("usage: artifact build|hash|sign|verify|keygen"))
	}
	command := os.Args[1]
	flags := flag.NewFlagSet(command, flag.ExitOnError)
	keyPath := flags.String("key", "", "PEM key path")
	signatureText := flags.String("signature", "", "base64 signature")
	directory := flags.String("directory", ".ferrule/keys", "development key directory")
	if err := flags.Parse(os.Args[2:]); err != nil {
		fail(err)
	}
	if command == "keygen" {
		if err := keygen(*directory); err != nil {
			fail(err)
		}
		fmt.Println("development-only keypair written to", *directory)
		return
	}

	path := ""
	if flags.NArg() > 0 {
		path = flags.Arg(0)
	}
	raw, err := input(path)
	if err != nil {
		fail(err)
	}
	built, err := artifact.Build(raw)
	if err != nil {
		fail(err)
	}
	switch command {
	case "build":
		fmt.Println(string(built))
	case "hash":
		fmt.Println(artifact.Hash(built))
	case "sign":
		keyPEM, err := os.ReadFile(*keyPath)
		if err != nil {
			fail(err)
		}
		key, err := artifact.ParsePrivateKeyPEM(keyPEM)
		if err != nil {
			fail(err)
		}
		signature, err := artifact.Sign(built, key)
		if err != nil {
			fail(err)
		}
		fmt.Println(base64.StdEncoding.EncodeToString(signature))
	case "verify":
		keyPEM, err := os.ReadFile(*keyPath)
		if err != nil {
			fail(err)
		}
		key, err := artifact.ParsePublicKeyPEM(keyPEM)
		if err != nil {
			fail(err)
		}
		signature, err := base64.StdEncoding.Strict().DecodeString(*signatureText)
		if err != nil || !artifact.Verify(built, signature, key) {
			fail(fmt.Errorf("verification failed"))
		}
		fmt.Println("verified")
	default:
		fail(fmt.Errorf("unknown command %q", command))
	}
}
