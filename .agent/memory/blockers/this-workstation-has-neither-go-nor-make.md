# This workstation had neither Go nor Make (RESOLVED)

**Date:** 2026-09-16
**Type:** blockers
**Status:** resolved 2026-09-16

This workstation originally had neither Go nor Make, so Python tests passed
locally but the Go conformance suite and `make gate-0a` could not run. The
original note was truncated by a bug in `memory-sync.mjs`'s bullet extraction
(it dropped word-wrapped continuation lines) — fixed in a later commit.

**Resolution:** Go (`go1.27.1`, `C:\Program Files\Go`, not on PATH by
default — prefix `export PATH="/c/Program Files/Go/bin:$PATH"` or add it
permanently) and Make (`GNU Make 4.4.1` via Chocolatey, on PATH) are now both
installed. `make gate-0a` runs literally and passes:

```
python -m unittest discover -s tests -v   -> 5 tests, OK
go test ./...                              -> ok
python tests/conformance.py                -> 20 Python/Go fixtures match
```

Milestone 0a is closed for real — no more manually re-running its
constituent commands by hand.
