# Changelog

Format: [Keep a Changelog](https://keepachangelog.com/). Versions here refer to
**specification** versions until code ships, then to releases.

---

## [Unreleased] — Process

### Known issues — Phase 0 + Phase 1 audit findings (2026-09-17)

Two independent audit passes (Codex fresh-context + Claude Code, each
verifying the other's and its own findings by direct reproduction, not
just static reading) found 11 real issues across Phase 0 and Phase 1.
None were new regressions — all were pre-existing gaps in already-gated
code. The 2 High findings were fixed the same day (2026-09-17, see "Fixed"
below); the remaining 9 stay deferred to before or during Phase 2 work.

**High — FIXED 2026-09-17**
- ~~Pagination continuation in the interpreter follows a response-supplied
  `next` URL (`offset`) or `Link` header (`link_header`) with no check
  against the plan's declared `hosts`~~ — fixed: `_request()` now validates
  a continuation URL's host against `plan.hosts` before issuing it, raising
  `UndeclaredHostError` instead of silently following an undeclared host.
  Re-reproduced the original attack against the patched code: exactly one
  request is made, the attacker host is never reached.
  `packages/interpreter/python/ferrule_interpreter/interpreter.py`.
- ~~`artifact diff` does not detect a field going from optional to
  required, any `enum`/`const`/`pattern`/bounds/`additionalProperties`
  tightening, or removal of an empty-schema output port~~ — fixed: field
  comparison now tracks requiredness (`became_required`/`became_optional`)
  and constraint changes (`constraint_changed`, naming which constraint),
  plus whole-port removal (`port_removed`). Breaking policy follows this
  project's own established convention (tightening the output contract is
  breaking, widening is visible but not breaking) — re-reproduced all
  three original blind spots directly against the patched code; all three
  now correctly report `breaking: true`, and the widening directions
  (required→optional, enum growing, a brand-new port) correctly stay
  `breaking: false`. Go has full parity coverage across every constraint
  type. `packages/artifact/{python,go}/*diff*`.

**Medium**
- `artifact diff`'s plan-change detection ignores step reordering and every
  plan-level field outside `steps` (including a bare-plan `hosts` change,
  which is invisible because `diff.py` only checks the full-node-manifest
  shape's `capabilities.hosts`, not milestone 1a's bare-plan top-level
  `hosts` — these two document shapes were never reconciled). Duplicate
  step IDs silently collapse to the last occurrence.
- Duplicate JSON object keys silently collapse to the last value before
  hashing/signing (confirmed identical last-wins behavior in Python and
  Go, so not a cross-language divergence, but a parser-differential risk
  against any other tool using first-key-wins semantics).
- Dev-keygen overwrite protection (`exists()`/`Stat()` then write) is
  TOCTOU-vulnerable to a race or symlink swap between check and write.
  Impact limited by this being dev-only tooling.
- The interpreter has no bound on a single response's byte size or decoded
  JSON size — 100 pages (the pagination cap) of arbitrarily large bodies
  can exhaust worker memory. Partly a deferred control (`SPEC.md` §4.1
  assigns `max_output_bytes` enforcement to the Phase 2 proxy), but the
  interpreter itself has no defense today.
- Request rendering in the interpreter doesn't sort query parameters or
  normalize header casing, violating invariant 5 (canonical/deterministic
  rendering) — two semantically identical plans can render different byte
  sequences, which is exactly the false-denial risk the Phase 2 proxy
  comparison is fragile to.

**Low**
- Python and Go **disagree on acceptance** of an unpaired UTF-16 surrogate
  escape (e.g. `"\ud83d"` with no matching low surrogate): Python's
  canonicalizer rejects it with `CanonicalizationError`; Go's
  `encoding/json` silently substitutes U+FFFD and proceeds. Valid
  surrogate pairs (real astral characters) match correctly in both.
- Deeply nested input (500+ levels) raises an uncaught `RecursionError` in
  the Python canonicalizer, bypassing the CLI's documented
  `CanonicalizationError`/`TypeError`/`ValueError` error contract.
- `chmod(0o600)` on the dev private key happens after the write (a brief
  POSIX race window under the process umask) and is a no-op ACL-wise on
  Windows regardless.
- CRLF injected into a rendered header value (via a crafted `input`/
  `response` field) is blocked by Python's stdlib `http.client` before it
  reaches the wire — not an actual injection vector — but the interpreter
  doesn't translate that rejection into a controlled `PlanRejected`; it's
  an unhandled `ValueError` that happens to get caught by the CLI's broad
  handler.

**Checked and confirmed fine, no gap:** CEL's namespace restriction under
macro-local variable shadowing (`map(secret, secret)` compiles but is
provably harmless — `evaluate()`'s activation never binds a real `secret`
value regardless of what the compile-time check permits); schema closure
on `stringMap`/`mapping` values (nested objects/arrays correctly rejected);
route status-key precedence (exact → Nxx → default); mock server's
`socket.getaddrinfo` patch restores correctly even when `run()` raises
partway through.

### Added — milestone 1c interpreter and mock execution

- Added the Python restricted-plan interpreter with mandatory static checking,
  deterministic templates, CEL response mapping, status routing, and bounded
  cursor, offset, link-header, and non-paginated execution.
- Added a loopback-only fixture server, `ferrule plan run-mock`, coverage
  classification, and 15 recorded plans spanning GitHub, Stripe, PokeAPI,
  JSONPlaceholder, and Open-Meteo geocoding.
- Closed schema escape hatches for non-HTTP URLs, unknown fields, and excessive
  pagination with a 100-page maximum, backed by 11 negative schema tests.

### Added — milestone 1b CEL integration and cost limits

- Wired `cel-python` (`celpy`) into the plan-schema checker: `map`,
  `when`/`condition`, and route-mapping CEL expressions are now
  compile-checked, not just validated as non-empty strings.
- Added a namespace-restriction static check (AST walk over celpy's parse
  tree) limiting expressions to `input`/`response` only — `secret` is
  structurally unreachable from CEL, per invariant 1. Comprehension locals
  (`filter`/`map`/`all`/`exists`/`exists_one`) are scoped correctly.
- Added a cost limit as a killable subprocess wall-clock timeout (1s
  evaluation budget, 10s startup budget): `cel-python` 0.5.0 has no native
  evaluation-step/cost accounting, so this substitutes for it. Documented as
  a v1 judgement call, not a claim that celpy has real cost budgeting.
- Added a standard-library function allowlist test — nothing beyond CEL's
  built-in functions is registered.
- `mypy --strict` and `ruff` clean; no regression on milestones 0a–1a
  (independently re-verified, not just re-stated from the build report).

### Added — milestone 1a static plan checker

- Added the draft 2020-12 restricted-plan schema, CEL context declarations,
  static findings for template syntax, declared hosts, bounded pagination and
  default routes, plus the `ferrule plan check` JSON-lines CLI.
- Added four valid and four invalid hand-written plan fixtures and a guard that
  prevents HTTP-client or process-execution imports from entering this package.
- Added `make gate-1a`; this gate is Python-only because plan execution and the
  Go proxy implementation belong to later milestones.

### Added — milestone 0c artifact diff

- Added deterministic Python and Go manifest diffs for output schemas, plans,
  and capabilities, including conservative breaking-change classification.
- Added `ferrule artifact diff`, five real manifest fixture pairs, and the
  `make gate-0c` milestone gate.

### Added — milestone 0a canonicalization

- Added byte-identical Python and Go canonical JSON implementations, a
  `ferrule artifact canonicalize` command, and 20 shared conformance fixtures.
- Added rejection of NaN and Infinity and property coverage for idempotence
  and object-key order independence.
- **Verified for real**, not just claimed: Go was installed on the dev
  machine and `python tests/conformance.py` confirmed all 20 fixtures are
  byte-identical between the Python and Go canonicalizers; `go build ./...`
  and `go test ./...` both pass. Milestone 0a's actual point — cross-language
  agreement — now has evidence, not just Python-only test output.
- Fixed a bug in `agent-os/scripts/memory-sync.mjs`: it only captured the
  first physical line of a word-wrapped Markdown bullet, silently dropping
  continuation lines. A recorded blocker about missing Go/Make lost its
  actionable half to this before being caught and corrected.

### Added — multi-agent workflow

- **`AGENTS.md` added** as the Codex-facing counterpart to `CLAUDE.md`.
  Invariants, repository layout and phase discipline are identical between
  the two; only tool-specific workflow mechanics differ. Keep them in sync.

### Changed — phase gates

- **`docs/PHASES.md` restructured**: every phase is now broken into
  sequential milestones (e.g. phase 2 → 2a–2d), each with its own
  deliverables, test criteria, security criteria and gate command
  (`make gate-2a`, etc.). The phase-level gate is the union of its
  milestones' gates.

  *Reason:* phase-sized gates (some spanning 8-10 checks across a Go proxy,
  credential broker and adversarial suite) were too coarse a unit for two
  agents/tools working the same phase side by side, and too coarse to catch
  a regression early — e.g. phase 2's canonicalization-determinism check is
  now its own milestone (2a) instead of buried alongside credential-broker
  work (2c) that depends on it.
  *Consequences:* milestones inside a phase are sequential and are the unit
  of work handoff between agents; do not open milestone N+1 before N's gate
  is green.

---

## [0.2] — Specification revision

Revision following external review of the 0.1 documents. Four substantive
corrections, one naming change, one deployment decision.

### Changed — security model (breaking)

- **Request authorization is now plan-bound.** The proxy independently re-derives
  each outbound request from the signed plan and compares, rather than checking
  a coarse host/method/secret manifest.

  *Reason:* 0.1 could not support its own claim. `GET api.customer.com/*`
  permits reading every endpoint on that host, so "a node built to read invoices
  cannot reach anywhere else" was false as specified.

  *Consequences:* step inputs must be journaled before dispatch; the proxy needs
  artifact access in the data plane; template rendering must be canonical and
  deterministic. The capability manifest is retained as defence-in-depth only
  and never widens what the plan permits.

- **Expression language changed from a hand-rolled interpreter to CEL.**

  *Reason:* hand-written expression evaluators are where "safe" DSLs leak. CEL is
  non-Turing-complete by design with built-in cost limits and a maintained
  Python implementation. No custom extension functions in v1.

### Changed — claims (accuracy)

- **Determinism claim narrowed.** 0.1 said "same recorded inputs, same result."
  That is false for live external calls. The guarantee is now: the same approved
  plan runs, execution is fully traced, and recorded-response replay is
  deterministic. Live results are explicitly not guaranteed.

- **Model pinning reworded** from implied reproducibility to
  **configuration-pinned and fully traced**. Hosted models drift beneath a
  version label.

- Added `SPEC.md` §2.2, an explicit list of what Ferrule does **not** guarantee.

### Changed — drift detection

- **Added baseline maturity states.** Detection does not run until a node reaches
  `baselined`. v1 ships `learning` mode only, with no alerting.

  *Reason:* a node approved on three sandbox fixtures has no idea what normal
  looks like. Alerting from a thin baseline is how the feature becomes noise.

- **Severity is now scoped to mapped fields.** A change to a field the node's
  output schema does not read is `info`, not `critical`. This single rule
  removes most false positives.

- **Added a confirmation ladder.** Observe → confirm → compute blast radius →
  alert and mark `at_risk` → quarantine only on high confidence and explicit
  policy. Never quarantine on a single observation.

- **Fixture replay against live APIs restricted to `read_only` nodes**, enforced
  in code. Idempotency keys protect against duplicates, not against a replayed
  cancellation being a legitimate cancellation.

- Added a required false-positive corpus (nullable fields, empty arrays, account
  tier variation, legitimate new enum values) as a phase gate.

### Changed — scope

- **Canvas removed from v1.** The buyer already has orchestration. Value is the
  artifact, not the boxes. The CLI and API are the v1 interface.
- v1 narrowed to: OpenAPI ingest, GET only, API-key and bearer auth, single-step
  plans, CLI, drift learning mode.
- Prose/PDF documentation ingest moved to phase 8 (last).

### Added — deployment

- **Target platform is Render.** Private Services for everything except `web`
  and `api`; dedicated outbound IPs before any pilot; external object storage
  for artifacts, fixtures and traces.

- **Documented the honest limit:** Render provides no per-container kernel-level
  egress policy. The v1 security guarantee is therefore **structural** (no
  untrusted code exists in the worker) rather than network-enforced. This holds
  only while the runtime is declarative; a custom-code tier must run elsewhere.

- Latency targets relaxed for PaaS reality: interpreter cold start 100 ms → 300
  ms, proxy added latency 15 ms → 25 ms.

### Added — instrumentation

- **`plan_coverage` is recorded on every compile attempt**, including failures.
  This number decides whether the custom-code tier is a v3 nicety or a v1
  requirement. Target: ≥ 70% `representable`. A formal decision point is placed
  at the phase 3 gate.

- Every pilot or test must record **the form real documentation arrived in**.
  The wedge is private APIs, which rarely ship OpenAPI — if most real docs are
  PDFs and Postman collections, phase 8 moves to the front.

### Changed — naming

- Project renamed from **D&D** to **Ferrule**. "D&D" is unsearchable and
  collides with a large trademark. Trademark and domain checks still outstanding.

### Noted — unresolved

- **Read-only-first is the right security order and a weak commercial test.**
  Implementation-team pain is disproportionately writes. One idempotent write
  behind an approval gate belongs in the first pilot with a paying conversation
  attached.
- **Coding agents are the real substitute**, not Zapier or n8n. Benchmarks must
  be set against an engineer using a coding agent with existing CI.
- **Path not chosen.** Portfolio-first is assumed in `PHASES.md`. The startup
  path front-loads a concierge validation study instead.

---

## [0.1] — Initial specification

- Product description, architecture and specification documents.
- Core thesis: sell what happens *after* AI generates integration code —
  verification, permission enforcement, immutable signed artifacts, credential
  isolation, durable execution, post-deployment drift detection.
- Restricted declarative plan as the default runtime instead of arbitrary code.
- Control plane / data plane split.
- Content-addressed, signed node artifacts with provenance and source-linked
  claims.
