# This workstation has neither Go nor Make (RESOLVED — Go installed)

**Date:** 2026-09-16
**Type:** blockers
**Status:** partially resolved 2026-09-16

This workstation originally had neither Go nor Make, so Python tests passed
locally but the Go conformance suite and `make gate-0a` could not run. The
original note was truncated by a bug in `memory-sync.mjs`'s bullet extraction
(it dropped word-wrapped continuation lines) — fixed in the same commit that
resolved this blocker.

**Update:** Go was installed manually (`go1.27.1 windows/amd64`, at
`C:\Program Files\Go`, not on this shell's PATH by default — prefix commands
with `export PATH="/c/Program Files/Go/bin:$PATH"` or use a fresh shell).
Verified directly:
- `go build ./...` and `go test ./...` from the repo root both pass.
- `python tests/conformance.py` — **all 20 fixtures byte-identical** between
  Python and Go. This is milestone 0a's actual point and it now has real
  evidence behind it, not just Python-only tests.

**Still open:** `make` itself is not installed (the Chocolatey install for it
failed alongside Go's — see below), so `make gate-0a` has not been invoked
literally, only its equivalent commands run by hand. Install `make` (or GNU
Make via choco/scoop in an elevated shell) before treating `make gate-0a` as
a real CI-equivalent check on this machine.
