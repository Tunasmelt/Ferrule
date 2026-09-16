# Project jargon — Ferrule

Terms this project uses in a specific way. Read every turn alongside
memory/index.md. Keep it short — this is vocabulary, not documentation.

Say the term, not the paragraph.

| Term | Means |
|------|-------|
| canonical bytes / canonicalization | The one deterministic UTF-8 encoding of a manifest value — sorted keys, plain decimal numbers, no exponents, no insignificant zeroes, `-0` → `0`. Python and Go must produce byte-identical output; divergence causes false denials in the proxy (phase 2). |
| conformance suite | The Python↔Go test that feeds the same 20 fixtures through both canonicalizers and diffs the bytes. Lives at `tests/conformance.py`; `make gate-0a` runs it. Requires Go + Make — currently unverified on this machine. |
| artifact_hash | `sha256(canonical(manifest) \|\| plan \|\| fixtures)`. Workflows reference this, never a slug (invariant 3). |
| plan_coverage | Per-compile verdict: `representable` / `representable_partial` / `not_representable`. Recorded on every compile attempt, including failures — decides whether the custom-code tier is needed. |
| plan-bound authorization | The proxy re-derives the expected request from the signed plan itself and compares, rather than checking a coarse capability manifest. The core security mechanism (SPEC.md §4.1). |
| milestone | A lettered sub-step inside a `docs/PHASES.md` phase (e.g. `0a`, `2b`), each with its own gate command (`make gate-0a`) and its own claim in `.agent/orchestration/claims.json`. The unit of work handoff between Claude Code and Codex. |
| claim / claim ledger | `.agent/orchestration/claims.json` — a file-based mutex so Claude and Codex never work the same milestone concurrently. See `agent-os/scripts/claim.mjs`. |
| dispatch | One bounded `codex-task.mjs` call: one milestone, one prompt, one sandbox. Codex runs non-interactively and returns; Claude reviews and gates. |
| node (integration node) | A signed, immutable artifact carrying its own schema, permissions, tests and provenance for one API operation. Not the same "node" as a workflow graph node — same word, check context. |
| CEL | Common Expression Language — the only expression language the plan format permits (invariant 7). Never `eval`, never Jinja with attribute access. |
