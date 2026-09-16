package main

import (
	"fmt"
	"io"
	"os"

	artifact "ferrule/packages/artifact/go"
)

func main() {
	input, err := io.ReadAll(os.Stdin)
	if err == nil {
		input, err = artifact.Canonicalize(input)
	}
	if err != nil {
		fmt.Fprintln(os.Stderr, err)
		os.Exit(1)
	}
	os.Stdout.Write(input)
}
