# Memory index — Ferrule

This project's decision record is `CHANGELOG.md` at the repo root, not this
tiered-memory system — `CHANGELOG.md` is human-curated, already the
convention here, and reviewed on every commit. `memory-sync.mjs` is **not
run** in this project; it would just re-record the same decisions a second
time as scattered single-fact files (that happened once — see the 2026-09-16
CHANGELOG entry "Close milestone 0a" note about the bug, and the cleanup that
followed). Blockers and gotchas go in `HANDOFF.md`'s Gotchas section instead.

If a future decision genuinely doesn't belong in `CHANGELOG.md` (something
too granular or too provisional to be worth a changelog entry), add it here
directly as a normal pointer line — don't run `memory-sync.mjs` to generate
one automatically.

Format: `DATE | TYPE | summary (<=150 chars) | -> path`
