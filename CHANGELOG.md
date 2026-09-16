# Changelog

Format: [Keep a Changelog](https://keepachangelog.com/). Versions here refer to
**specification** versions until code ships, then to releases.

---

## [Unreleased] — Process

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
