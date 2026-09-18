# Ferrule — Phases, Milestones and Gates

Each **milestone** is a command with an exit code, not a judgement call. A
milestone is closed when its gate command exits 0 in CI and its listed
artifacts exist. A **phase** is closed only when every milestone inside it is
closed and the phase-level gate (the union of milestone gates, plus any
whole-phase checks) exits 0.

Do not build ahead of the current milestone's gate. Do not start a
milestone's deliverables before the previous milestone in the same phase is
green — milestones inside a phase are sequential, not parallel, unless
explicitly marked "parallelizable" below.

**Ordering principle: enforcement before generation.** Phase 2 precedes phase
3 deliberately. Retrofitting a security model onto a working generator is the
failure mode that kills products in this category. The same principle applies
inside phases: the milestone that makes something rejectable comes before the
milestone that makes it convenient.

**Naming convention:** milestone gates are `make gate-<phase>-<letter>`, e.g.
`make gate-2b`. The phase gate `make gate-<phase>` runs all of that phase's
milestone gates plus any phase-only check and is what `docs/HANDOFF.md` and
`CLAUDE.md`/`AGENTS.md` refer to as "the gate."

**Handoff unit for multi-agent work (Claude Code + Codex side by side):** a
milestone, not a phase. Claim a milestone before starting it; do not open a
second milestone in the same phase until the first's gate is green, since
later milestones usually depend on the data model or interfaces the earlier
one froze.

**Status convention:** a milestone heading gets `— ✅ CLOSED <date>` appended,
and its checkboxes flip to `[x]`, only after its gate command has actually
been run and passed — not when the work merely looks done. Update this file
in the same commit that closes the gate; don't let it drift from
`CHANGELOG.md`.

## Progress

| Phase | Milestones closed | Status |
|---|---|---|
| 0 — Artifact format | 0a ✅ / 0b ✅ / 0c ✅ | **closed** |
| 1 — Plan language | 1a ✅ / 1b ✅ / 1c ✅ | **closed** |
| 2 — Proxy & broker | 2a ✅ / 2b ✅ / 2c ✅ / 2d ✅ | **closed** |
| 3 — Compiler (OpenAPI) | 3a–3c ⬜ | not started |
| 4 — Verification & evidence | 4a–4c ⬜ | not started |
| 5 — Durable execution | 5a–5c ⬜ | not started |
| 6 — Drift, learning mode | 6a–6c ⬜ | not started |
| 7 — Drift detection | 7a–7c ⬜ | not started |
| 8 — Prose doc ingest | 8a–8b ⬜ | not started |

Update this table in the same commit that closes a milestone's gate.

---

## Phase 0 — Artifact format

**Goal:** the artifact idea is real, hashable, signable and diffable.

### Milestone 0a — Canonicalization core — ✅ CLOSED 2026-09-16

Deliverables
- [x] `packages/artifact` (Python): canonical byte-serialization of the manifest
  structure (sorted keys, fixed number formatting, no locale dependence)
- [x] Go port of the same canonicalization function
- [x] `ferrule artifact canonicalize` CLI command (prints canonical bytes, for
  diffing against the Go output by hand during development)

Test criteria
- [x] Property test: canonicalization is idempotent (`canon(canon(x)) == canon(x)`)
- [x] Property test: canonicalization is order-independent (shuffled map/dict
      key order produces identical output)
- [x] Cross-language conformance: Python and Go produce byte-identical output
      for 20 fixture manifests, including edge cases (empty arrays, nested
      objects, unicode strings, large integers)

Security criteria
- [x] Canonicalizer rejects (does not silently coerce) NaN/Infinity in numeric
      fields — these are non-canonical across JSON implementations

Gate `make gate-0a` — **passing** (verified 2026-09-16: `python -m unittest
discover -s tests -v` — 5/5 tests; `go test ./...` — ok; `python
tests/conformance.py` — 20/20 fixtures byte-identical). Built by Codex via
`codex-task.mjs`, verified independently by Claude Code after installing
Go/Make on the dev workstation. See `CHANGELOG.md` [Unreleased] for detail.
Exit when: fixtures pass in both languages and the property tests pass. — met.

### Milestone 0b — Hash, sign, verify — ✅ CLOSED 2026-09-16

Deliverables
- [x] `packages/artifact` build/hash/sign/verify (ed25519) in Python
      (`cryptography`) and Go (stdlib `crypto/ed25519`)
- [x] `ferrule artifact {build,hash,sign,verify}` CLI commands, plus a
      dev-only `keygen` command not in the original spec but needed to
      generate the local keypair the other four commands depend on
- [x] Local key generation for dev signing (documented as dev-only, not for
      anything resembling production custody; overwrite-protected, private
      key written `0600`, `.ferrule/keys/` gitignored)

Test criteria
- [x] Round-trip: build → sign → verify passes for the same 20 fixture
      artifacts from 0a
- [x] Any single-byte mutation of a signed artifact fails verification
- [x] Verification fails closed on a missing, truncated, or wrong-length
      signature (no exception that could be caught and ignored by a caller)
- [x] Verification fails on a signature valid for a *different* artifact's
      hash (no cross-artifact signature reuse)
- [x] (added beyond the original spec) bidirectional cross-language
      verification: a Python-produced signature verifies in Go and vice
      versa, across all 20 fixtures

Security criteria
- [x] Dev signing key is never committed; `.gitignore`/CI check confirms
- [x] Verify path does not accept an "unsigned" or "skip verification" mode
      via any flag or environment variable — confirmed by reading both
      `verify()` implementations directly, not just by the tests passing

Gate `make gate-0b` — **passing** (verified 2026-09-16, independently
re-run, not just accepted from Codex's self-report: 11/11 Python tests,
`go test ./...` ok, 20/20 canonicalization fixtures, 20/20 cross-language
signature fixtures both directions; `ruff` + `mypy --strict` clean). Built
by Codex via `codex-task.mjs`. Scope decision (Codex's, reviewed and
accepted): `artifact_hash = sha256(canonical(manifest))` only — the
`|| plan || fixtures` part of `SPEC.md`'s formula is deferred until those
artifact sections exist. See `CHANGELOG.md` [Unreleased] for detail.
Exit when: sign/verify round-trips and mutation/cross-artifact tests pass in
both languages. — met.

### Milestone 0c — Diff — ✅ CLOSED 2026-09-16

Deliverables
- [x] Artifact diff (schema changes, plan changes, capability changes, breaking
      flag) matching the shape in `docs/API.md`'s
      `GET /nodes/.../diff` response
- [x] `ferrule artifact diff` CLI command

Test criteria
- [x] Diff between two versions of the same 5 fixture artifacts (modified by
      hand) produces stable, human-readable output
- [x] Diff correctly flags `breaking: true` when an output port gains a
      required field, and `false` when a field is only added as optional or
      to an unmapped path
- [x] Diff output is itself deterministic (running twice on the same pair
      produces byte-identical output)

Gate `make gate-0c` — **passing** (verified 2026-09-16, independently
re-run: 15/15 Python tests including the new diff suite, `go test ./...`
ok; `make check`/`make conform` re-run clean to confirm no 0a/0b
regression). Built by Codex via `codex-task.mjs`. Judgement call (Codex's,
reviewed and accepted): when a port's schema has no explicit `required`
array, any newly added field on an existing port is conservatively treated
as breaking; when `required` is present, only listed fields count. Only
`schema_changes` on an *existing* output port drives `breaking` — a brand
new port, and any `plan_changes`/`capability_changes`, are never breaking on
their own, matching the "severity scoped to mapped fields" principle from
`SPEC.md` §6.3. Verified by hand that fixture pair 02 reproduces `API.md`'s
own documented example exactly. See `CHANGELOG.md` [Unreleased] for detail.
Exit when: diff fixtures pass and breaking-change classification is correct
on all 5 hand-modified pairs. — met.

### Phase 0 gate — ✅ CLOSED 2026-09-16

`make gate-0` = `gate-0a` + `gate-0b` + `gate-0c`, plus:
- [x] All three CLI command groups (`canonicalize`, `build/hash/sign/verify`,
      `diff`) are reachable from a single `ferrule artifact` entrypoint —
      confirmed: `ferrule artifact --help` lists
      `{canonicalize,build,hash,sign,verify,keygen,diff}` under one parser.

Exit when: `make gate-0` exits 0. — **met, all of Phase 0 is closed.**

---

## Phase 1 — Plan language and interpreter

**Goal:** plans can express real integrations, and only those.

### Milestone 1a — Static plan structure and checker — ✅ CLOSED 2026-09-16

Deliverables
- [x] `packages/plan-schema` — JSON Schema (draft 2020-12) for the plan
      (steps, templates, pagination, routing) and a CEL type-context stub
      for milestone 1b to build on
- [x] Static checker: schema validity, bound template variables, declared
      hosts, default route present, pagination bounded

Test criteria
- [ ] Static checker accepts 15 hand-written valid plans (see 1c) — **not
      yet met by design**: PHASES.md itself says not to wait for 1c, and only
      4 synthetic valid fixtures (one per pagination mode) exist so far. This
      box stays unchecked until 1c's 15 real-API plans exist and pass.
- [x] Static checker rejects: unbound template variable, undeclared host,
      unbounded pagination, missing default route (4 cases minimum, one per
      failure kind) — 4/4 present, one fixture each, verified independently.
      **Added 2026-09-18** (5th case, beyond the original minimum): duplicate
      step `id` — the schema has no uniqueness constraint on it, so a
      schema-valid plan could have two steps sharing an id, which the proxy's
      `findStep` (milestone 2b) resolves ambiguously (first match always
      wins). Found during 2b's dedicated audit as a milestone 1a gap, not a
      2b one, and fixed here rather than in the proxy: `check()` now emits
      `DUPLICATE_STEP_ID`, fixture `duplicate-step-id.json` added.

Security criteria
- [x] Static checker runs before any plan reaches the interpreter — there is
      no interpreter code path that accepts an unchecked plan, even in
      tests. **Met by scope, not by enforcement**: no interpreter exists yet
      (that's milestone 1c) — this milestone shipped no HTTP client,
      template renderer against live data, or execution path at all,
      verified by a real test that scans the package source for
      requests/httpx/urllib.request/subprocess/os.system, plus a manual grep
      by Claude Code independent of that test.

Gate `make gate-1a` — **passing** (verified 2026-09-16, independently
re-run: 20/20 Python tests including the new plan-schema suite; `make
check`/`make conform` re-run clean, no Phase 0 regression). Built by Codex
via `codex-task.mjs`. Judgement call (Codex's, reviewed and accepted): a
bare plan document needs its own top-level `hosts` field, since `SPEC.md`'s
example only shows hosts inside a full node manifest's `capabilities`
block. No Go implementation in this milestone — correctly deferred to Phase
2, where the proxy is the thing that actually needs to re-render plans in
Go. See `CHANGELOG.md` [Unreleased] for detail.

### Milestone 1b — CEL integration and cost limits — ✅ CLOSED 2026-09-16

Deliverables
- [x] CEL evaluation wired into the mapping/condition/routing layer (via
      `cel-python`/`celpy`; `map`, `when`/`condition` expressions in
      milestone 1a's checker are now compile-checked, not just validated as
      non-empty strings)
- [x] Configured max cost per expression (see note below); strict
      namespace-restriction checking at compile time; no custom CEL
      extension functions registered

Test criteria
- [x] CEL typecheck rejects an untyped/ill-typed expression at compile time,
      not at run time — **narrower than full CEL type inference**: celpy
      0.5.0 does not provide static type inference, only parsing +
      annotation acceptance, so what's actually enforced at compile time is
      namespace restriction (only `input`/`response`, never `secret` or
      anything else) via an AST walk. This is a real, verified guarantee,
      just not the same shape as a fully-typed CEL implementation would give.
      Documented explicitly rather than silently overclaiming.
- [x] A deliberately expensive CEL expression (large cartesian comprehension)
      is terminated by the cost limit rather than run to completion —
      verified with a genuine O(n²) nested `exists` comprehension over
      10,000 elements, forcibly killed via a subprocess timeout.
- [x] Negative test: no CEL extension function beyond the standard library is
      registered (enumerate registered functions in a test and assert against
      an allowlist) — allowlist checked against real CEL builtin functions.

Security criteria
- [x] No code path evaluates a plan expression with `eval`, a template engine
      with attribute access, or any evaluator other than the configured CEL
      runtime (grep-based CI check, not just a manual review)

Gate `make gate-1b` — **passing** (verified 2026-09-16, independently
re-run: 28/28 Python tests; `make check`/`make conform` re-run clean, no
regression on 0a–1a). Built by Codex via `codex-task.mjs`. Judgement call
(Codex's, reviewed and accepted): `cel-python` 0.5.0 has no native
evaluation-cost/step budget, so the "max cost per expression" requirement is
met with a killable subprocess wall-clock limit (1s evaluation, 10s
startup) instead — a real, enforced limit, just implemented as a wrapper
around the library rather than a feature the library provides natively.
Secrets are structurally unreachable from CEL: the evaluation context
declares only `input`/`response`, never `secret` (invariant 1). See
`CHANGELOG.md` [Unreleased] for detail.

### Milestone 1c — Interpreter and mock execution — ✅ CLOSED 2026-09-17

Deliverables
- [x] Plan interpreter (Python): HTTP steps (stdlib `http.client`), CEL
      mapping, response routing, pagination
      (`cursor`/`offset`/`link_header`/`none`), all bounded by `max_pages`
- [x] Local mock HTTP server for tests (stdlib `http.server`)
- [x] `ferrule plan {check,run-mock}` CLI commands
- [x] 15 hand-written plans against 5 real public APIs (GitHub, Stripe,
      PokeAPI, JSONPlaceholder, Open-Meteo geocoding), recorded as fixtures
      against the mock server, never live — test execution patches
      `socket.getaddrinfo` only inside the mock run's context manager to
      redirect every hostname to the local fixture server while the real
      `Host` header is preserved for fixture selection.

Test criteria
- [x] All 15 plans execute correctly on mock (correct route selected,
      correctly mapped output shape) — verified independently, including a
      fresh classifier re-run against each execution fixture, not just the
      pre-recorded coverage artifact.
- [x] `plan_coverage` classifier runs and emits a verdict for each of the
      15 — all 15 record `representable`, which is the correct and expected
      result for hand-picked, checker-passing plans (not a shortcut — the
      other two verdicts get real exercise once Phase 3's OpenAPI compiler
      can produce plans that aren't hand-picked to fit).
- [x] Negative test suite: **11** cases (one over the required minimum) —
      filesystem path field, `exec`/`shell`/`command` fields, `file://` URL,
      `pagination: "unbounded"`, method `"EXEC"`, nested `steps` (recursion
      attempt), `max_pages` over the new 100 cap, an ad-hoc `loop` field, an
      `imports` field — each proven to fail **schema validation**
      specifically, not merely rejected by application code.

Security criteria
- [x] Interpreter has no code path that reads an environment variable, the
      filesystem, or system time into a template or CEL evaluation context —
      a guard test scoped to `interpreter.py`/`render.py`/`coverage.py`
      specifically (not the mock server, which legitimately reads fixture
      files as test infrastructure). Secret markers (`{{ secret.X }}`)
      render to an inert, unresolved placeholder string — verified by
      reading `render.py` directly: there is no code path that could read a
      real secret value, and there is nothing to read yet at this stage
      regardless.
- [x] Hard execution gate: the interpreter calls 1a's `check(plan)` before
      building any request and refuses to run if it returns findings —
      proven with a transport stub that raises `AssertionError` if ever
      invoked, not just a heuristic ("points at nothing") test.

Gate `make gate-1c` — **passing** (verified 2026-09-17, independently
re-run: 34/34 Python tests; fresh `make gate-1a`/`make gate-1b` re-run
clean, no regression). Built by Codex via `codex-task.mjs`. Found and fixed
two real schema gaps while building the negative suite: plan URLs are now
restricted to `http`/`https` (closing a `file://` escape 1a's schema left
open), and `max_pages` is now required for `link_header` pagination too
(1a only required it for `cursor`/`offset`) and capped at 100 — 1a's own
`multiple-link-header` fixture was updated to stay valid under the tighter
schema. See `CHANGELOG.md` [Unreleased] for detail.

**Known limitation for the record** (not a blocker — all 15 real plans
work correctly): pagination continuation checks
`route_name in ("ok", "results")` to decide whether to fetch the next page.
A plan whose success route is named something else would silently stop
paginating after page one even with more pages available. Worth revisiting
once Phase 3's compiler can produce arbitrarily-named success routes.

### Phase 1 gate — ✅ CLOSED 2026-09-17

`make gate-1` = `gate-1a` + `gate-1b` + `gate-1c`.

Exit when: `make gate-1` exits 0. — **met, all of Phase 1 is closed.**

**Instrument from here:** every plan written by hand during this phase
records whether the target operation was fully representable. This is the
first real data on the number from `SPEC.md` §3.4.

---

## Phase 2 — Plan-bound proxy and credential broker

**Goal:** the core security claim holds under adversarial test. **This phase,
and milestone 2b in particular, is the most important gate in the project.**

### Milestone 2a — Artifact access and request re-derivation — ✅ CLOSED 2026-09-17

Deliverables
- [x] `services/proxy` (Go) skeleton: `Authorize(cache, journal, request)`
      taking a struct matching
      `{ node_version_hash, run_id, step_seq, step_id, step_input_digest,
      canonicalized_request }` — a plain Go function API, not a network
      listener; wiring behind `net/http` is left to the milestone that
      actually has something on the other end of the wire
- [x] `ArtifactCache`: `Push` (verifies signature via
      `packages/artifact/go` before caching, immutable once cached — no
      update path) and `Get`; `Push` is not reachable from any
      network-facing surface (there isn't one in this milestone)
- [x] `RunJournal` interface + in-memory implementation: records a step's
      input and its `sha256(canonical(input))` digest before authorization
      can reference it, stands in for the real Postgres-backed journal
      phase 5 will build behind the same interface
- [x] Independent Go re-rendering of a step's URL/headers/query/body
      (`RenderRequest`), reproducing
      `packages/interpreter/python/ferrule_interpreter/render.py` and
      `interpreter.py`'s `_request` canonicalization rules byte-for-byte:
      marker substitution, secret markers preserved verbatim (never
      resolved — no secret resolution exists anywhere in this milestone),
      sorted merged query params, title-cased sorted headers, compact
      sort-keys JSON body with Python's `ensure_ascii=True` escaping
      (verified against unicode/astral-character fixtures, not assumed from
      Go's `encoding/json` defaults)

Test criteria
- [x] Proxy fetches and verifies a pushed artifact's signature before using
      it — a tampered artifact is rejected by `Push` and never retrievable
- [x] Proxy denies (does not process) a request whose `step_id` is absent
      from the plan
- [x] Proxy denies a request whose `step_input_digest` does not match the
      journal row for `(run_id, step_seq)`
- [x] Canonicalization determinism: 1,000 renders of the same step input
      produce byte-identical requests (a real 1,000-iteration loop, not a
      token gesture)

Security criteria
- [x] Proxy has no "trusted" or "bypass" code path reachable by any request
      shape, header, or flag — enforced by a real Go test that scans every
      non-test `.go` file under `services/proxy` for `skip_verify`,
      `bypass`, `trusted`, `danger_full_access` as identifiers, not just a
      manual review
- [x] Proxy artifact cache is read-only from the proxy's own perspective —
      confirmed by reading `cache.go` directly: `Push` is Go-API-only, no
      HTTP/RPC surface exists in this package at all yet

Gate `make gate-2a` — **passing** (verified 2026-09-17, independently
re-run: `go test ./services/proxy/... -v` and `go test ./...` both green;
`make check`/`make conform` re-run clean, no regression on phases 0–1).
Built by Codex via `codex-task.mjs`.

**Caught during independent review** (same defect class as milestone 0c's
plan-diff gap): Codex's `findStep` only looked for steps nested under a
`manifest["plan"]["steps"]` key — the shape `SPEC.md` section 5 shows for a
*full future node manifest* — and its own test fixtures used exactly that
shape, so its tests passed while never exercising the plan document this
codebase actually produces today. Every plan document that milestone 1a's
schema validates and milestone 1c's interpreter executes has `steps` at the
*top level*, with no `plan` wrapper at all. Reproduced directly: pushed a
real bare-plan-document artifact (`{"hosts": [...], "steps": [...]}`) through
`Authorize` and confirmed `findStep` reported "step not found" for a step
that was actually present. Fixed directly in `authorize.go` by falling back
to treating the manifest itself as the plan when no `plan` key exists —
same fix shape as the earlier `diff.go`/`diff.py` correction. Added
`TestAuthorizeAcceptsBarePlanDocumentShape` as a permanent regression test
using the real shape. Re-verified `gate-2a` green after the fix.
Exit when: fixture proxy tests pass and determinism/denial cases hold. — met.

**Second audit pass (2026-09-17), post-close — 4 more findings, all fixed
same day:** requested a dedicated 2a audit; Claude Code did an independent
read + reproduction pass, then dispatched Codex for a second independent
read-only pass over the same code with no knowledge of the first pass's
findings. Two findings were caught independently by both: `Authorize`
always rendered with a `nil` previous-step context even though
`{{ response.x }}` markers bind to the previous step's output (a real
fixture, `tests/fixtures/plans/valid/cursor.json`, depends on this for
pagination) — raised to **High** given Codex's sharper framing: this can
let a worker's genuinely divergent request coincide with the proxy's
wrongly-empty re-derivation, not just cause false denials. And the
`TestNoForbiddenIdentifiers` regex never matched Go-idiomatic camelCase/
PascalCase names (`SkipVerify`, `IsTrusted`) since `\b` doesn't fire inside
a camelCase transition — **Medium**, a false security assurance in the
test itself. Codex's pass also caught two Claude Code missed: header-name
collisions after title-casing resolve differently in Python (tie-break by
value after `sorted()`) vs. Go (tie-break by raw key) — **Medium**; and
U+007F (DEL) wasn't escaped by the Go body serializer though Python's
`ensure_ascii=True` does escape it — **Low**. All four independently
verified by Claude Code via direct reproduction before fixing. Fixed the
response-context gap directly (journal entries now carry a canonical
`{input, previous}` envelope, digest covers both); dispatched the other
three to Codex as two bounded tasks (the identifier-detection rewrite
alone in `proxy_test.go`; the two `render.go` canonicalization fixes
together, since they share a file). Re-verified `gate-2a`, `make check`,
`make conform`, full `go test ./...` all green after every fix, no
regression. See `CHANGELOG.md` for detail.

### Milestone 2b — Request comparison and denial paths — ✅ CLOSED 2026-09-18

Deliverables
- [x] Comparison of independently-rendered request against the worker-submitted
      `canonicalized_request`; any divergence → DENY + security event
      (`services/proxy/authorize.go`)
- [x] Redirect policy (no cross-host redirects; same-host redirects count against
      budget), per-step request budget, max response bytes, content-type
      allowlist (`services/proxy/forward.go`)

Test criteria
- [x] Proxy denies a request whose URL differs from the re-derived plan step
      (`TestAuthorizeDeniesSubmittedURLMismatch`)
- [x] Proxy denies a host not in the plan, even if present in the capability
      manifest (this is the test that proves invariant: manifest is
      defence-in-depth only) — `TestAuthorizeDeniesHostAbsentFromPlanHosts`
      uses a fixture where `capabilities.hosts` would permit the request and
      `plan.hosts` would not, and confirms only the latter is consulted
- [x] Proxy denies a method not in the plan step — `TestAuthorizeDeniesSubmittedMethodMismatch`.
      Scope decision (reviewed and accepted): there is no separate
      method-specific check; the plan step is the sole source of the method,
      so a worker submitting a different one already fails the byte
      comparison above. A dedicated `method_mismatch` code was considered
      and rejected as redundant.
- [x] Proxy denies a cross-host redirect; a same-host redirect is allowed but
      counts against the step's request budget and a 4th same-host redirect
      on a 3-redirect budget is denied — `TestForwardDeniesCrossHostRedirectWithoutFetchingTarget`,
      `TestForwardRedirectBudget` (both the exactly-3-succeeds and the
      4th-denied cases, asserting the exact transport call count in each).
      Precisely defined to remove the ambiguity in this bullet's own wording:
      `ForwardPolicy.MaxRedirects` counts redirects only: the initial request
      is free, `MaxRedirects=3` permits 4 total requests, and a would-be 5th
      is never sent.
- [x] Proxy denies a response exceeding `max_output_bytes` — `TestForwardDeniesOversizedResponse`
- [x] Proxy denies a disallowed content type — `TestForwardContentTypeAllowlist`
      (matches the media-type portion only, ignoring a `; charset=...` suffix)
- [x] Request budget per step is enforced (Nth request in a step that permits
      N-1 is denied) — same mechanism and same tests as the redirect-budget
      bullet above; this project's "per-step request budget" and "redirect
      budget" are one mechanism, not two, since every request after the
      first in a single step's authorization is, by construction, a redirect
      follow.

Security criteria
- [x] Every denial in this milestone emits a security event distinguishable
      from a plain application error — `SecurityEvent` (`services/proxy/security_event.go`)
      is a typed, JSON-tagged struct with a stable `Code`, carried on
      `Decision.SecurityEvent`/`Forward`'s return value, not a bare `error`.
      Milestone 2a's own earlier denial reasons (artifact/step/journal/digest)
      were left as plain `Reason` strings, out of this milestone's scope.
- [x] Injection probe: a response body containing instruction-shaped text
      changes nothing about subsequent request construction —
      `TestForwardIgnoresResponseBodyInstructions`. Scope note recorded
      honestly rather than overclaimed: there is no code in Go yet that
      builds a "next step's request" from a previous response body (that
      CEL-based response routing/mapping exists only in the Python
      interpreter and has not been ported). What this milestone's `Forward`
      actually controls — redirect-following, size/content-type checks, what
      is returned to the caller — is proven to depend only on status code,
      headers, and body *length*, never on body text content.

Gate `make gate-2b` — **passing** (verified 2026-09-18, independently
re-run: `go test ./services/proxy/... -v` and `go test ./...` both green;
`make check`/`make conform`/`gate-2a` re-run clean, no regression). Built
by Codex via `codex-task.mjs` in two bounded dispatches (comparison +
host enforcement; then forwarding + redirect policy), each independently
verified. Codex correctly refused to edit `proxy_test.go` when dispatched
the comparison work even though two of its fixtures predated comparison
enforcement (a stub submitted request, an undeclared host) — those
fixtures were updated directly afterward rather than weakening the new
checks. Two real issues were caught during my own full-Go-codebase review
after both dispatches landed and fixed directly, not by Codex: (1) the
cross-host redirect check compared `Hostname()` only, so an
`https → http` redirect to the identical hostname (a scheme downgrade)
was treated as same-host and followed — a real credential-leak vector
the moment milestone 2c injects secrets into forwarded headers; fixed by
comparing full origin (scheme + host), with
`TestForwardDeniesSchemeDowngradeRedirect` as a permanent regression
test. (2) a JSON-decode failure on the independently-rendered request was
mislabeled with security-event code `undeclared_host` instead of its own
code, which would have miscounted an internal rendering fault as a
host-authorization violation in later drift/alerting; given its own code
`invalid_rendered_request`. A `staticcheck` SA6005 finding
(`strings.ToLower(a) == strings.ToLower(b)` instead of `strings.EqualFold`)
in the same host-comparison function was fixed the same way.

**Dedicated audit pass (2026-09-18), post-close — 2 more findings fixed,
2 recorded as tracked follow-ups:** Claude Code did an independent read
pass, then dispatched Codex for a second independent read-only pass with
no visibility into the first pass's findings; both converged on the same
two real issues.
- **Fixed (Medium):** `Forward` took a `Decision` *and* a separate
  `AuthorizationRequest` parameter with nothing tying them together — a
  caller could authorize step A, then call `Forward` with step A's
  `Decision` alongside step B's `AuthorizationRequest`, sending A's
  request while attributing any `SecurityEvent` to B's identifiers. Not
  presently reachable (no orchestrator/caller exists yet), but a real gap
  in the API contract the next milestone would build on. Fixed by moving
  `NodeVersionHash`/`RunID`/`StepSeq`/`StepID` onto `Decision` itself
  (populated by `Authorize`) and dropping `Forward`'s second parameter
  entirely — there is no longer a second identity value that could
  disagree with the `Decision`.
- **Fixed (Low):** `TestAuthorizeAcceptsBarePlanDocumentShape` was named
  as an acceptance test but submitted a stub request that fails the
  milestone-2b byte comparison and asserted only `decision.StepFound` —
  misleading coverage (it never proved full authorization succeeds
  against the bare-plan shape). Renamed to
  `TestFindStepAcceptsBarePlanDocumentShape` with a comment pointing to
  `TestAuthorizeAcceptsMatchingRequest`, which already covers full
  acceptance of this same shape.
- **Follow-up fixed 2026-09-18 (was: Medium correctness / Low current
  security impact):** `packages/plan-schema`'s JSON Schema had no
  uniqueness constraint on step `id`, and the Python checker didn't add
  one either — a schema-valid plan could have two steps sharing an `id`.
  `findStep` returns the first match, so the second occurrence could never
  be authorized (fails the byte comparison against the wrong step's
  rendering) — this failed closed, not open, so it was never an
  authorization bypass, but it was a milestone 1a gap. Fixed in 1a's own
  package rather than in the proxy: `check()` now emits
  `DUPLICATE_STEP_ID` (see milestone 1a's test-criteria note above for
  detail); re-verified full `python -m unittest discover` clean, no
  regression on 0a–1c.
- **Follow-up fixed 2026-09-18 (was: Medium for whichever milestone adds a
  real transport; no current exploit):** `Forward`'s response-size check
  compared `len(response.Body)` only after `Transport` had already
  returned a fully-buffered body — correct against the mock transports
  used in tests, but a real transport would need to enforce the limit
  *while reading*, not after, or an oversized response becomes a
  memory/bandwidth exhaustion vector before the denial ever fires. Fixed
  by changing `Transport`'s signature to
  `func(OutboundRequest, maxResponseBytes int) (OutboundResponse, error)`
  — `Forward` now passes `policy.MaxResponseBytes` to the transport on
  every call, so any real implementation has the bound available to
  enforce during acquisition — plus a new `BoundedRead(io.Reader, int)
  ([]byte, error)` helper any real transport should call instead of
  `io.ReadAll`, using the same "read one byte past the limit" technique
  as `packages/interpreter/python/ferrule_interpreter/interpreter.py`'s
  `_http()`. `Forward`'s own post-hoc length check remains as
  defense-in-depth against a transport that ignores the contract.
  `TestBoundedReadRefusesOversizedSource` and
  `TestForwardPassesResponseByteLimitToTransport` added as permanent
  tests. This still doesn't build a real `net/http` transport — that
  remains for whichever milestone actually needs one — but the contract
  it must honor, and a tested helper for honoring it, now exist.

Exit when: comparison/host/redirect/budget/size/content-type denial tests
pass and the injection probe holds. — met.

This is the single highest-priority gate in the project. Do not let CI treat
it as advisory — a red `gate-2b` blocks everything downstream of phase 2.

### Milestone 2c — Credential broker and injection — ✅ CLOSED 2026-09-18

Deliverables
- [x] Credential store with `broker_ref` indirection
      (`services/proxy/credentials.go`) — in-memory, thread-safe, no
      exported method returns a raw value (only an unexported `resolve`
      reachable from this package's own resolution code). No Postgres
      exists anywhere in this codebase yet, matching the same scope
      decision already made for `RunJournal`/`ArtifactCache` in 2a. No
      workspace/binding-management system exists either, so a plan's
      secret NAME → `broker_ref` binding is supplied directly by the
      caller as an explicit `SecretBindings` map
      (`services/proxy/secrets.go`) rather than a persisted binding
      layer — documented as a deliberate v1 scope boundary, not an
      oversight.
- [x] Secret resolution (`ResolveSecrets` in `secrets.go`): `{{ secret.NAME }}`
      markers are matched using the exact same marker regex `render.go`
      already uses (no separately-written, potentially-divergent regex),
      and substituted only inside `Forward` -- strictly after
      `Authorize` has already succeeded on the *unresolved* placeholder
      form, and only into a copy consumed for the actual outbound send.
      `authorize.go` and `render.go` were not modified: the comparison
      that proves a worker's request matches the plan still runs entirely
      on unresolved placeholder text, exactly as before.
- [x] Redacted capture: `redact.go`'s `Redact` strips every resolved
      secret value (longest-first, so a shorter value can't leave a
      fragment of a longer one exposed) from the response body and every
      response header before `Forward` returns it to its caller.

Test criteria
- [x] Secret marker in a plan template resolves correctly to the bound
      credential's value inside the proxy —
      `TestForwardResolvesSecretAfterAuthorization` authorizes a request
      with `{{ secret.acme_erp_api_key }}` in a header, forwards it, and
      confirms the transport received the real resolved value.
- [x] **Met by scope, not by a working scan**: there is no `POST
      /credentials` endpoint, no structured logging system, and no trace
      capture anywhere in this codebase yet (no HTTP server exists for
      any milestone through 2c), so this criterion's literal automated
      scan has nothing to scan. What's actually enforced today:
      `CredentialStore`'s public API has no method that returns a raw
      value at all (`TestCredentialStoreDeleteIsIdempotent`'s trailing
      comment records this as the package's public-API contract), so
      there is no code path capable of writing one anywhere, log or
      otherwise. Revisit this box for real when an HTTP/log layer exists.
- [x] **No credential material appears in any worker-visible surface** —
      the architectural boundary from Phase 1 already holds unchanged
      (the worker is `packages/interpreter`, in a different language,
      and structurally never runs code capable of resolving a secret
      marker; `render.py` still only ever produces the placeholder
      string). What milestone 2c adds on top: `TestForwardRedactsEchoedSecretFromResponse`
      proves that even if an upstream API reflects a resolved secret back
      in its response body or a header (the concrete "error message
      echoes a credential" scenario this criterion names), `Forward`
      strips it before returning. Grepped every `fmt.Errorf`/`errors.New`/
      `fmt.Sprintf` call added in this milestone's files by hand: none
      embed a raw resolved secret value.
- [x] Deleting a credential causes the next run bound to it to fail with
      failure class `auth`, not a generic error — `FailureClassError{Class:
      "auth"}` (`secrets.go`), proven end to end by
      `TestResolveSecretsFailsWithAuthAfterCredentialDeletion`: resolve
      succeeds, delete the credential, the next resolution attempt fails
      with the typed class, checked via `errors.As`, not string-matching.

Security criteria
- [x] Redaction happens before the trace/log write, not as a
      post-processing pass — met by scope for the same reason noted
      above (no trace/log write exists yet to redact before); the
      redaction that does exist (`Forward`'s response path) runs inline,
      synchronously, before the response value is ever handed back to a
      caller — there is no "capture now, clean up later" step anywhere
      in this milestone's code to grep for.

Gate `make gate-2c` — **passing** (verified 2026-09-18, independently
re-run: `go test ./services/proxy/... -v` and `go test ./...` both green;
`make check`/`make conform`/`gate-2a`/`gate-2b` re-run clean, no
regression). Built by Codex via `codex-task.mjs`.

**Caught during independent review**: `ResolveSecrets` used Go's
`strconv.Quote` to embed a resolved secret value into the JSON envelope's
string content. `strconv.Quote` produces *Go* string-literal escaping,
not JSON escaping -- for certain control bytes (e.g. a bell character,
`0x07`) it emits `\a`, which is not a valid JSON escape sequence at all.
Reproduced directly: a credential containing such a byte produced a
malformed JSON envelope that failed `json.Unmarshal` inside `Forward`'s
`decodeOutboundRequest`, meaning any run using that specific credential
would fail outright. Fixed by reusing `render.go`'s own
`writePythonString` (the same JSON-safe escaping already used everywhere
else in this package) instead of `strconv.Quote`. Added
`TestResolveSecretsEscapesControlByteAsValidJSON` as a permanent
regression test.

**Dedicated audit pass (2026-09-18), post-close — 4 more findings, 3
fixed, 1 tracked:** requested a dedicated 2c audit given it's the first
code in this project to ever hold a real secret value. Claude Code did
an independent pass first, then dispatched Codex for a second,
independent, read-only pass with no visibility into the first pass's
findings.
- **Fixed (Medium, found by Claude Code):** `CredentialStore` had no
  `String()`/`GoString()` method. Go's `fmt` package prints unexported
  fields under `%v`/`%+v`/`%#v` via reflection, ignoring normal field
  visibility -- reproduced directly: `fmt.Sprintf("%+v", store)` dumped
  every stored credential verbatim. An accidental debug/log call on a
  `*CredentialStore` anywhere, now or in the future, would have leaked
  every secret it held. Fixed by adding both methods, returning only a
  count. `TestCredentialStoreFormattingDoesNotLeakValues` added.
- **Fixed (High, found independently by both passes, Codex reproduced
  it first and concretely):** `Redact` only matched a secret's exact raw
  bytes. An upstream echoing a credential back inside its own JSON
  response re-escapes characters like a literal quote (`"` → `\"`), and
  the raw-value search never matches the escaped substring — reproduced
  directly: a credential containing a `"` survived redaction in a
  simulated JSON error-echo response. Threat model: a malicious or even
  merely diagnostic-happy upstream that has just received a resolved
  credential can trivially cause this by reflecting it in a structured
  error body. Fixed with a bounded, deliberately partial mitigation (URL
  encoding, base64, and other transformations remain unbounded and are
  not chased): `Redact` now also searches for each secret's
  JSON-string-escaped form, built with the same `writePythonString`
  escaper `ResolveSecrets` uses to embed values into JSON in the first
  place. New `TestRedact/JSON-escaped_echo` case.
- **Fixed (High, found by Codex, independently reproduced by Claude
  Code):** `SecurityEvent.Reason` for the post-resolution denial paths
  (`cross_host_redirect`, `request_budget_exceeded`, `response_too_large`,
  `disallowed_content_type`) was built directly from response metadata an
  upstream fully controls -- a `Content-Type` header value, a redirect's
  `Location` host -- and was never passed through `Redact`, unlike the
  success-path response. Reproduced directly and concretely: an upstream
  setting its `Content-Type` response header to literally be the resolved
  secret value caused `SecurityEvent.Reason` to contain the raw secret,
  verbatim, in a value returned to the caller — while the disallowed
  content type also happened to be the correct fail-safe outcome, the
  leak in the *event describing* that outcome is exactly what invariant 1
  exists to prevent. A related, lower-likelihood path (Medium, also
  fixed): a transport implementation that formats request details into
  its returned `error` (common in real HTTP client libraries) would have
  had that error passed back verbatim. Fixed both: `forwardDenied` now
  redacts `reason` before constructing the `SecurityEvent`, and a
  transport error's text is redacted before `Forward` returns it.
  `TestForwardRedactsSecretFromDenialReason` and
  `TestForwardRedactsSecretFromTransportError` added.
- **Follow-up fixed 2026-09-18 (was: Medium today, would become High if
  exposed without change):** `Forward` trusted only the exported
  `decision.ChecksPassed` boolean, with nothing structurally tying a
  `Decision` to a real `Authorize()` call — a caller could construct
  `Decision{ChecksPassed: true, RenderedRequest: "...{{ secret.X }}..."}`
  directly and obtain full secret resolution and forwarding with no
  artifact lookup, journal check, host check, or byte comparison ever
  having run. Fixed with Go's own package-visibility boundary rather than
  a runtime token: `Decision` now carries an additional unexported
  `verified` field that only `Authorize`'s success path sets, and
  `Forward` requires it alongside `ChecksPassed`. A caller outside
  `package proxy` cannot set an unexported field at all — not "is
  discouraged from", literally cannot, it's a compile error — so the
  *only* way to produce a `Decision` `Forward` will act on is a real call
  to `Authorize` that reaches its success path. Code inside this package
  (including its own tests, which legitimately need to fabricate
  decisions to unit-test `Forward` in isolation) is unaffected — that's
  the intended boundary, not a hole in it.
  `TestForwardRejectsChecksPassedWithoutAuthorize` proves a
  same-package-but-not-through-`Authorize` construction is still
  rejected, which is as close as a single package's own test suite can
  get to proving the cross-package case without a second package to test
  from. Whatever milestone eventually adds a real caller in a different
  package (2d's permission-probe suite, or whichever milestone builds the
  actual network entry point) inherits this guarantee automatically
  rather than needing to re-derive it.

Exit when: secret resolution, deletion failure class, and redaction tests
pass. — met.

### Milestone 2d — Adversarial verification suite — ✅ CLOSED 2026-09-18

Deliverables
- [x] Permission probe suite as a standalone, repeatable adversarial test
      harness (`services/proxy/probe.go`'s exported `RunPermissionProbes`,
      not test-only code — it takes an already-running proxy's base URL and
      an environment to register fixtures against, so phase 4 can reuse it
      unchanged against a differently-hosted proxy instance later)
- [x] Latency benchmark harness (`services/proxy/latency_test.go`, local
      mock, controllable rps)
- [x] (Beyond the original deliverables, required to make either of the
      above possible) `services/proxy/http_transport.go`: the project's
      first real `net/http`-backed `Transport`, and `services/proxy/server.go`:
      the project's first real HTTP server, exposing `POST /v1/authorize`
      and wrapping `Authorize`+`Forward`. Milestone 2d's own test criteria
      require "a running proxy instance" and "black-box HTTP tests" — that
      requires an actual server and outbound transport to exist for the
      first time, so building them was this milestone's necessary, not
      incidental, first half.

Test criteria
- [x] Permission probe suite runs all of 2b's and 2c's denial/injection cases
      against a running proxy instance as black-box HTTP tests — 12/12
      cases, every one driven as a real HTTP POST against a real
      `httptest`-hosted server using the real `HTTPTransport` (not a mock)
      talking to its own real local adversarial upstream: submitted URL
      mismatch, capabilities-cannot-widen-plan-hosts, method mismatch,
      cross-host redirect (with a call counter proving the target is never
      fetched), same-host redirect budget (both within-budget success and
      over-budget denial), oversized response, disallowed content type,
      injection-probe inertness (verified against an equal-length control
      body, headers/status compared for exact equality), secret resolution
      end-to-end (verified by inspecting the real header the mock upstream
      received), deleted-credential auth failure, response-echo redaction,
      and denial-metadata redaction.
- [x] p95 added latency < 25 ms under 50 rps against a local mock —
      measured p95 ≈ 530–570 µs over 150 requests paced at 50 rps
      (real numbers from repeated runs, not a single cherry-picked one),
      comfortably under the 25 ms bar; expected to be this low since
      everything is loopback/in-process with no real network hop.
      **Fixed 2026-09-18, flagged by `/code-review`**: this is a real
      wall-clock assertion, flaky on a loaded/shared machine through no
      fault of the proxy code — and since `gate-2a`/`gate-2b`/`gate-2c`
      all run the same unfiltered `go test ./services/proxy/...` (no
      per-milestone test binary split), it was silently running under all
      three, meaning timing noise could fail an unrelated milestone's
      gate. Changed the test to skip by default, opting in only via
      `FERRULE_LATENCY_BENCHMARK=1`, which only `gate-2d` sets — confirmed
      it now shows `SKIP` (0.00s) under `gate-2a`/`2b`/`2c` and runs for
      real only under `gate-2d`.

Gate `make gate-2d` / `make security` — **passing** (verified 2026-09-18,
independently re-run repeatedly). Built by Codex via `codex-task.mjs` in
two bounded dispatches (the server+transport; then the probe suite+latency
benchmark), each independently verified.

**Caught during independent review of the first dispatch, fixed before
building the second:** `server.go` copied the upstream's `Content-Length`
header through to the caller unchanged. `Forward`'s redaction (milestone
2c) can change `response.Body`'s length relative to what the upstream
declared, since a secret and `"[REDACTED]"` are rarely the same length.
Reproduced in complete isolation from this codebase before touching any
file: writing a body whose real length differs from a copied, smaller,
stale `Content-Length` makes Go's own `net/http` **client** read zero
bytes for the entire response and report `"unexpected EOF"` — not a
graceful truncation. This would have made virtually any real request that
triggered redaction unreadable by any standard HTTP client. Fixed by
omitting `Content-Length` and `Transfer-Encoding` from the copied headers
and letting `net/http` compute the correct one from what is actually
written. `TestServerOmitsStaleContentLengthAfterRedaction` added, driving
a real HTTP round trip that would have failed with `"unexpected EOF"`
before the fix.

**Caught by Codex during the second dispatch, correctly reported rather
than worked around out of scope, then fixed directly:** two real gaps at
the boundary between the new HTTP surface and existing `forward.go`/
`server.go` (both files Codex was correctly told not to touch for that
dispatch):
- A real `Transport` enforcing `MaxResponseBytes` via `BoundedRead` (as
  its own doc comment already said it should) returned a plain untyped
  `error` on overflow, which `Forward` then returned as a generic error
  instead of a `response_too_large` `SecurityEvent` — the mock-transport
  unit tests never caught this because mock transports just returned an
  oversized `OutboundResponse` value directly, letting `Forward`'s
  separate post-hoc length check catch it instead. Fixed with a new typed
  `ResponseTooLargeError` that `BoundedRead` returns and `Forward`
  recognizes via `errors.As`, converting it into the same `SecurityEvent`
  the mock-transport path already produced.
- `ResolveSecrets`' `*FailureClassError` (milestone 2c, `"auth"` on a
  deleted credential) was silently discarded into the same generic
  `"upstream request failed"` message as any other `Forward` error,
  losing exactly the distinction failure classes exist to carry (SPEC.md
  §7: `auth` means no retry). Fixed in `server.go` by recognizing
  `*FailureClassError` and responding `403` with a `failure_class` field
  — `403` because this is an authorization-shaped failure, matching the
  pre-`Forward` denial responses, not an upstream problem.
Both fixes verified by re-running the probe suite Codex had already
written (which correctly expected this behavior and failed honestly
against the pre-fix code) — 12/12 probes pass after the fixes, one probe
assertion's expected status code (403, not 502) was corrected to match
the actual, reviewed design decision made when fixing the second gap.

Exit when: permission probe suite and latency benchmark pass. — met.

### Phase 2 gate — ✅ CLOSED 2026-09-18

`make gate-2` = `gate-2a` + `gate-2b` + `gate-2c` + `gate-2d`.

Exit when: `make gate-2` exits 0 **and** `make security` exits 0. — **met,
all of Phase 2 is closed.** The core security claim (SPEC.md §2.1: no
request a plan doesn't already describe, no credential reaching the
worker) now has independently-verified, adversarially-tested, real-HTTP
evidence behind it, not just unit tests against internal functions.

**Whole-phase audit (2026-09-19), post-close — 1 High fixed, 1 Low fixed,
5 tracked:** every prior 2a/2b/2c/2d audit was scoped to its own
milestone's files. This one deliberately looked across all of
`services/proxy` together for problems that only exist at the
integration level. Claude Code did an independent pass, then dispatched
Codex for a second independent read-only pass with no visibility into
the first pass's findings; Codex found the most serious issue.

- **Fixed (High):** `MemoryRunJournal` was keyed only by `(run_id,
  step_seq)`, with no binding to which artifact or step a journal entry
  was actually recorded for. Reproduced directly and concretely: a
  destructive step in one signed artifact was **fully authorized** using
  a read-only step's journal entry from a completely different artifact,
  sharing only `run_id`/`step_seq`/digest — a real confused-deputy gap in
  the core binding the whole proxy exists to enforce. Fixed by recording
  `NodeVersionHash` and `StepID` on every `JournalEntry` and having
  `Authorize` reject a mismatch (`journal_step_mismatch`) before ever
  reaching the digest check. `TestAuthorizeRejectsJournalEntryFromWrongArtifactAndStep`
  added (with a companion assertion that a legitimate matching request
  still succeeds).
- **Fixed (Low):** `decodeAuthorizationRequest` read the `/v1/authorize`
  request body with an unbounded `json.Decoder`, so an unauthenticated
  network client could send an arbitrarily large body before the JSON
  decode ever failed. Fixed with `http.MaxBytesReader` (1 MiB, matching
  the existing response-body-size convention).
  `TestServerRejectsOversizedRequestBodyOverHTTP` added.
- **Fixed 2026-09-19 (was: Tracked, High):** authorization was fully
  replayable — a successful `Authorize`+`Forward` had no single-use
  marker, and `Forward`'s redirect/request budget was a fresh local
  variable on every HTTP call, so anyone who captured one accepted
  request could resubmit it indefinitely, re-executing the upstream side
  effect and getting a fresh budget each time. Fixed: `JournalEntry`
  gained a `Consumed` flag; `Authorize` denies (`replay_denied`) any
  further authorization of an entry that already delivered one complete
  response. This does not break legitimate retries: CLAUDE.md already
  establishes the run journal as append-only, so a retry (whether after a
  transient failure or a retryable upstream response) is expected to be
  journaled under a *new* `step_seq`, never by resubmitting the same one
  — marking consumed after any fully-delivered response (the proxy
  correctly never interprets upstream HTTP status as success/failure,
  that's the interpreter's routing job) is therefore the right proxy-level
  granularity. `server.go` marks the entry consumed immediately before
  writing the successful response, not after, so a write failure can't
  leave a delivered side effect replayable.
  `TestServerDeniesReplayOfCompletedRequest` added.
- **Fixed 2026-09-19 (was: Tracked, Medium):** `POST /v1/authorize` had no
  authentication of its caller. Fixed with a shared-secret bearer check
  (`Server.AuthToken`, compared with `crypto/subtle.ConstantTimeCompare`)
  — proportionate to there being no other auth mechanism anywhere in this
  project yet. An unset `AuthToken` fails closed (denies every request)
  rather than silently disabling authentication.
  `TestServerRequiresAuthentication` added (missing header, wrong token,
  and the fail-closed-with-no-token-configured case).
- **Fixed 2026-09-19 (was: Tracked, Medium):** `SecretBindings` was a
  plain unsynchronized `map[string]string`, unlike `ArtifactCache`/
  `MemoryRunJournal`/`CredentialStore`, which all use a mutex. Converted
  to a mutex-guarded struct (`NewSecretBindings`/`Bind`/an unexported
  `resolve`) across every call site. `TestSecretBindingsConcurrentAccessDoesNotPanic`
  added.
- **Fixed 2026-09-19 (was: Tracked, Medium):** `ForwardPolicy` was a
  single process-wide value the caller supplied, never derived from a
  signed artifact's own `runtime_limits` (SPEC.md §5) — two artifacts with
  different signed limits got the identical effective policy. Fixed:
  `Authorize` now parses an optional top-level `runtime_limits` block from
  the manifest onto `Decision.ArtifactLimits`, and a new
  `MergeForwardPolicy(serverPolicy, artifactLimits)` combines it with the
  caller's configured policy, taking the more restrictive numeric value
  and the intersection of content-type allowlists — the artifact can only
  ever tighten its effective policy, never widen it, matching the same
  principle already applied to hosts. `server.go` calls this before every
  `Forward`. `TestMergeForwardPolicyTakesMoreRestrictiveValues` and
  `TestServerEnforcesArtifactRuntimeLimitsOverServerPolicy` added (the
  latter drives a real HTTP round trip where the server alone would allow
  a response the artifact's own tighter limit correctly denies).
- **Fixed 2026-09-19 (was: Tracked, Low):** failure classification
  (SPEC.md §7) was incomplete — no `SecurityEvent` carried a named failure
  class, and network/transport errors surfaced as an unclassified generic
  502. Fixed: `SecurityEvent` gained a `FailureClass` field, set to
  `"permission_denied"` for every denial in this package (an unauthorized
  or policy-violating request is exactly what that class means: no retry,
  security event). A new `TransportError` type carries `"timeout"` or
  `"transient"` for network/connectivity failures (classified from the
  original error via `net.Error`'s `Timeout()` *before* its text is
  redacted, since a redacted error is just a string by then and loses that
  type information). Errors that are neither a `FailureClassError`, a
  `TransportError`, nor a `SecurityEvent` (a decode failure, a nil
  transport, an invalid rendered URL — internal proxy faults SPEC's
  classes don't model, and effectively unreachable in practice) stay in
  the generic, unclassified bucket rather than being mislabeled with a
  class that doesn't fit them.
  `TestSecurityEventCarriesPermissionDeniedFailureClass` and
  `TestServerClassifiesTransportTimeoutAndTransientFailures` added.

All five tracked findings from this audit are now fixed. Also fixed along
the way: `probe.go`'s injection and deleted-credential probe cases used
to resubmit the same `(run_id, step_seq)` twice, which now correctly hits
replay protection — restructured to register a fresh journal entry per
case, matching what two truly independent workflow runs would do, plus a
`"_probe_name"` manifest discriminator so fixtures pointed at the same
test upstream stop colliding on `ArtifactCache.Push`'s content-addressed
immutability check. The latency benchmark now pre-registers 150 distinct
journal entries instead of resending one request 150 times, for the same
replay-protection reason (p95 unaffected: still comfortably under 25 ms
across repeated runs).

Re-verified against `gate-2a`/`2b`/`2c`/`2d`, `make security`, `make
check`, `make conform` — all green, no regressions. See `CHANGELOG.md`
for detail.

---

## Phase 3 — Compiler, OpenAPI path

**Goal:** generation accuracy on real specs.

### Milestone 3a — Ingest and operation resolution — ✅ CLOSED 2026-09-19

Deliverables
- [x] OpenAPI ingest (`services/compiler/python/ferrule_compiler/openapi.py`):
      parses JSON or YAML, validates the minimal required OpenAPI 3.x
      structure with distinct error types for "not valid JSON/YAML" vs.
      "valid but not OpenAPI", extracts one `Operation` per (path, method)
      with a stable synthesized `operation_id` fallback when the spec omits
      one, and computes a `sha256:<hex>` source hash matching the hash
      format already used elsewhere in this codebase.
- [x] Deterministic operation resolution (`resolve.py`): Jaccard word-set
      similarity over camelCase/kebab-case/path-segment-aware tokenization
      of `operationId`/summary/description/tags/path, with a minimum
      relevance floor (reject low-confidence guesses as `no_match`) and a
      ratio-based ambiguity band (candidates within 90% of the top score
      are all returned as `needs_input` options, not just the top two). No
      LLM call anywhere in this milestone — SPEC.md §8's "Builder model" is
      milestone 3b's concern (schema/plan generation), not operation
      resolution, and 3a's own test criteria are fully satisfiable
      deterministically.
- [x] `POST /sources`, `POST /sources/{id}/documents`,
      `POST /sources/{id}/extract` from `docs/API.md`, plus two additions
      beyond API.md's documented surface, both noted inline in `api.py`:
      `GET /sources/{id}/operations` (API.md's extract response only
      returns a count, not the queryable list this milestone's test
      criteria require) and `POST /sources/{id}/resolve` (API.md's
      resolution-with-ambiguity flow lives inside `POST /nodes/compile`,
      which also does schema/plan generation — milestone 3b's job, not
      built yet; 3a adds a narrower endpoint scoped to resolution only).
      `POST /jobs/{id}/resume` resolves a `needs_input` job with a chosen
      `operation_id`. In-memory, mutex-guarded store
      (`store.py`) standing in for Postgres, matching the same
      documented-stand-in pattern used throughout Phase 2's `RunJournal`/
      `ArtifactCache`/`CredentialStore`. No workspace-scoped API-key auth in
      this milestone — noted explicitly in `api.py` as a deliberate scope
      boundary, same as `services/proxy`'s single-shared-secret bearer
      token predating a full auth system.
- [x] 8 hand-authored OpenAPI 3.0 fixture excerpts under
      `tests/fixtures/openapi/` modeling real, currently-documented
      operations from GitHub, Stripe, PokeAPI, JSONPlaceholder, Open-Meteo,
      Slack, SendGrid, and Twilio (see that directory's `README.md` for the
      same "recorded fixture, not a live call" honesty framing established
      in milestone 1c).

Test criteria
- [x] 8 public OpenAPI specs ingest without error and produce a queryable
      operation list — `tests/test_compiler_ingest.py` ingests all 8
      fixtures and spot-checks specific known operations by
      operation_id/method/path, not just non-empty-list checks.
- [x] A deliberately ambiguous task description against a spec with two
      matching operations returns `needs_input` with both candidates, not a
      guess — `tests/test_compiler_resolve.py`: the task "Fetch a single
      resource by its numeric id" against `jsonplaceholder.json` resolves
      ambiguous with both `getPost` and `getUser` as candidates (and
      `getPostComments` correctly excluded); a closely-matching task
      resolves unambiguously to `getPost` alone; an irrelevant task
      ("launch a satellite into orbit") returns `no_match` rather than a
      low-confidence guess.
- [x] `POST /jobs/{id}/resume` with a chosen operation ID proceeds
      correctly — `tests/test_compiler_api.py` drives the full real HTTP
      flow via FastAPI's `TestClient`: create source → upload document →
      extract → list operations → resolve (unambiguous) → resolve
      (ambiguous, `needs_input`) → resume with a chosen operation_id →
      resolved. Malformed-body and unknown-source-id error paths verified
      against API.md's documented error envelope shape.

Gate `make gate-3a` — 16/16 tests pass; `make check` (72/72 Python tests,
`mypy --strict` clean on the new package, Go tests unaffected) and
`make conform` (20/20 fixtures) both still pass with no regressions.

Built by Codex via `codex-task.mjs` (dispatch hit a Codex usage-limit error
mid-task but had already completed the real work — package, tests, Makefile
target, pyproject.toml registration — before failing); independently
re-verified by Claude Code: read every new source file, ran `gate-3a`,
`make check`, `make conform`, and `mypy --strict` directly rather than
trusting the dispatch's self-report.

**Milestone 3a audit (2026-09-19)**, run by Claude Code across the whole
milestone rather than per-file, found and fixed 3 issues:
- **Medium — FIXED**: `upload_document` read an uploaded document with no
  size cap, and `openapi._load` falls back to `yaml.safe_load` on anything
  that isn't valid JSON — `safe_load` blocks code execution but not
  resource exhaustion from adversarial anchor/alias expansion on a small
  malicious upload. Same issue class as the unbounded-request-body finding
  already fixed for the proxy in the Phase 2 whole-phase audit, not carried
  over here. Fixed with a 10 MiB cap enforced via a bounded `file.read(...)`
  in `api.py`, returning `413 document_too_large`.
- **Medium — FIXED**: `resume_job` read a job then wrote it back as two
  separate `Store` lock acquisitions, so two concurrent resumes of the same
  `needs_input` job with different choices could both pass the status check
  before either wrote — the second write silently clobbered the first with
  no error, resuming a job twice. Same race class as Phase 2's SecretBindings
  finding. Fixed by adding `Store.resume_needs_input`, which holds one lock
  across the whole check-select-write sequence, making resume single-use by
  construction; verified with a threaded test
  (`tests/test_compiler_store.py`) asserting exactly one of two concurrent
  resumes succeeds.
- **Low — FIXED**: `_fallback_id`'s word-based tokenization drops path
  structure, so e.g. `/foo/bar` and `/foo-bar` (same method, no declared
  `operationId`) synthesize the identical fallback id — an undetected
  collision would let `resume_job`'s exact-id lookup silently resolve to
  the wrong operation. Fixed by disambiguating any duplicate operation id
  within one ingested document with a deterministic `-2`, `-3`, … suffix;
  covered by `test_colliding_fallback_ids_are_disambiguated`.

### Milestone 3b — Schema and plan generation — ✅ CLOSED 2026-09-19

**Scope decision, made with the user before writing any code**: generation
is deterministic template mapping, not an LLM-backed "Builder model".
SPEC.md §8 describes generation via a real model call with a regenerate-
on-failure loop; this milestone's actual test criteria (20+ real GET
operations, no request bodies) are fully satisfiable by mechanically
mapping OpenAPI path/query/header parameters into the phase-1 plan
language — no judgment call is required. A real LLM integration is a
product decision (provider, API key handling, cost controls) deferred to
whichever later milestone first needs it for cases this can't handle
(request bodies, ambiguous response shapes). Because generation here is
deterministic, the "regenerate-on-failure loop" degenerates to a single
attempt by construction (documented in `generate.py`'s module docstring):
the same operation always produces the same plan, so a static-check
failure means the mapping is unrepresentable, not a fixable mistake worth
retrying blindly.

Deliverables
- [x] Input/output port schema generation (`generate.py`'s `_input_schema`
      and the fixed `_OUTPUT_SCHEMA`) — `input_schema` built from each
      operation's path/query/header parameters (JSON Schema type mapped
      from the OpenAPI parameter schema, `required` set for path params
      always and query/header params per their declared `required`);
      `output_schema` is a fixed two-port shape (`ok`, `error`) since
      generic REST responses have no declared shape to derive ports from
      without parsing response schemas, which these fixtures mostly don't
      declare either.
- [x] Deterministic plan generation (`generate.py`'s `compile_operation`):
      one step per GET operation, path parameters substituted into the URL
      template, query/header parameters mapped into the step's `query`/
      `headers` maps, `200 -> ok` and `default -> error` routes each
      mapping the whole response/status. Returns `not_representable` (never
      a silently wrong plan) for: non-GET operations, a `cookie`-location
      parameter (no first-class support in the plan language), a parameter
      name that isn't a valid template/CEL identifier, or a `Source`
      `base_url` with no resolvable hostname.
      **3a's `Operation` model was extended** with a `parameters` field
      (new `Parameter` dataclass: name/location/required/schema_type,
      merging Path Item Object and Operation Object parameter lists per
      OpenAPI 3.x override semantics) — 3a's ingest never captured
      parameters at all, and plan generation needs them. `OperationResponse`
      gained the matching field; existing 3a tests unaffected (none
      asserted exact-equality on the full operation shape).
- [x] `plan_coverage` verdict recorded for every attempt, reusing 1c's
      existing `ferrule_interpreter.coverage.classify_plan` classifier
      rather than reimplementing it — every one of the 23 real GET
      operations gets `representable` or `representable_partial`, and the
      one deliberately-unrepresentable synthetic fixture gets
      `not_representable`, so this milestone is the first to give the
      classifier's `representable_partial` and `not_representable` verdicts
      real exercise (1c's own text flagged this as still owed).
      `representable_partial` is used honestly, matching SPEC.md's own
      definition ("fits except for N named transformations"): an optional
      query/header parameter always renders (empty string when unset
      — `render.py`'s `_lookup`) rather than being omitted from the
      request, since the plan language has no conditional-inclusion
      primitive — recorded as a named limitation, not silently ignored.
- [x] Fixtures extended from 13 to **23** real GET operations across the
      same 8 specs (2-3 more genuinely real, documented operations added to
      7 of the 8 files — `jsonplaceholder.json` deliberately left untouched
      since 3a's resolver tests depend on its exact 3-operation shape), plus
      one new, clearly-labeled **synthetic** fixture
      (`synthetic-cookie-param.json`, explicitly excluded from the "8 real
      specs" / "20 GET operations" counts, documented in the fixtures
      README) built specifically to exercise the `not_representable` path
      honestly with a `cookie`-location parameter, rather than forcing a
      fake requirement onto one of the real API fixtures.
- [x] All 5 first-party Python packages (`ferrule_artifact`,
      `ferrule_cli`, `ferrule_interpreter`, `ferrule_plan_schema`,
      `ferrule_compiler`) are now **actually editable-installed**
      (`pip install -e .`) rather than resolved only via ad hoc
      `sys.path.insert` in test files — `generate.py` is the first piece of
      application code (not test scaffolding) needing a real cross-package
      import (`ferrule_interpreter.coverage`, `ferrule_plan_schema`), which
      test-only `sys.path` hacks can't satisfy. Added a `py.typed` marker
      (PEP 561) to each package and registered it in
      `pyproject.toml`'s `package-data` so `mypy --strict` can resolve
      cross-package types without ad hoc `MYPYPATH` tricks going forward.

Test criteria
- [x] 20 GET operations across the 8 specs from 3a compile to plans that
      pass the phase-1 static checker — 23 real GET operations available
      (exceeds 20); `test_compiler_generate.py` compiles every one and
      independently re-runs `ferrule_plan_schema.check()` on each returned
      plan (not trusting `compile_operation`'s internal call), asserting
      zero findings for all 23.
- [x] `plan_coverage` recorded for all 20 (23), including any that fail to
      compile — every compile call returns a `CompileResult` with a
      `coverage` verdict; the synthetic cookie-parameter case and a non-GET
      operation both exercise the failure path with a recorded verdict and
      reasons, not an exception.
- [x] 100% of the 20 (23) either produce a valid plan or an explicit
      `not_representable` verdict — never a silently wrong plan that passes
      static checks. **Manual inspection performed**: 6 of the 23 generated
      plans (github `repos/get` and `issues/list-for-repo`, pokeapi
      `listPokemon`, open-meteo `getForecast`, slack `conversations.list`,
      twilio `ListMessage` — chosen to cover path-only, path+optional-query,
      query-only, no-parameters, and dotted-operation-id cases) printed in
      full and read by the reviewer, confirming correct URL templating,
      query mapping, host extraction (including a spec whose `base_url`
      has a path prefix, `pokeapi.co/api/v2`), and `input_schema`
      required/optional splitting. Reviewer: Claude Code, 2026-09-19.

Security criteria
- [x] Generated plans are static-checked (milestone 1a's checker) before
      being persisted as a `node_version` row in any status other than
      `draft` — generation cannot skip the checker via a different code
      path. No `node_version` persistence layer exists yet in this
      codebase (a later phase's concern), so this is enforced at the only
      point that currently exists: `compile_operation` has exactly one
      return path that yields a non-`None` `plan` (after `check_plan`
      returns zero findings), and `test_generated_plans_actually_pass_the_static_checker`
      independently re-runs the checker on every returned plan rather than
      trusting the internal call, closing the "different code path" gap
      this criterion is guarding against.

Gate `make gate-3b` (depends on `gate-3a`) — 25/25 tests pass (16 from 3a
+ 9 new); `make check` (81/81 Python tests), `mypy --strict`
(`services/compiler/python/ferrule_compiler` + `cli/ferrule_cli`, clean),
and `make conform` (20/20) all still pass with no regressions.

**Milestone 3b audit (2026-09-19)**, run by Claude Code by tracing how
`generate.py`'s URL construction interacts with `openapi.py`'s parameter
parsing and the checker's double-brace-only template grammar (a
cross-file interaction a narrow per-file review would miss), found and
fixed 2 issues:
- **High — FIXED**: `compile_operation` substituted only *declared*
  `"in": "path"` parameters into the URL via literal string replacement.
  A spec whose path contains a `{placeholder}` with no matching declared
  parameter (a documentation error), or whose declared name doesn't
  exactly match the placeholder text (e.g. a case difference), would
  silently leave a literal, unsubstituted single-brace segment in the
  generated URL — the checker's template grammar only recognizes
  double-brace `{{ ... }}` markers, so this passed schema validation, host
  checks, and CEL type-checking untouched: a plan reporting `representable`
  while being wrong at request time, exactly what this milestone's test
  criteria rule out. None of the 23 real fixture operations triggered it
  (all correctly declared), but the generator had no defense against one
  that doesn't. Fixed by checking the *raw* path's placeholder names
  against declared path-parameter names *before* substitution — checking
  the substituted string instead was tried first and was itself buggy (see
  below) since it also matches the inner `{ input.x }` of a legitimate
  `{{ input.x }}` marker.
  - Caught during verification, not before: the first fix attempt scanned
    the *substituted* URL for leftover single-brace segments, which
    incorrectly flagged every legitimate `{{ input.x }}` marker as a stray
    placeholder (a `{{...}}` marker contains a matching `{...}` substring)
    and broke 3 previously-passing tests. Re-running the full 3b suite
    immediately after applying the fix caught this before it was
    considered done — corrected by matching against the raw pre-substitution
    path instead, verified against all 23 real operations plus new
    regression tests for both the undeclared and case-mismatched cases.
- **Medium — FIXED**: `openapi.py`'s parameter merge dedupes by
  `(name, location)`, so a `path` parameter and a `query` parameter sharing
  the same name (e.g. both named `id`) are kept as two distinct
  `Parameter` entries — but `generate.py` mapped every parameter to the
  same `input.<name>` template variable regardless of location, so both
  would silently read from one shared input port even if they represent
  different values (and `_input_schema`'s dict comprehension would let one
  silently overwrite the other's declared type). Not triggered by any of
  the 23 real fixture operations. Fixed by rejecting a cross-location name
  collision as `not_representable`; covered by a new regression test.

Full 3b suite re-verified after both fixes: 28/28 `gate-3b` tests (16 from
3a + 12 from `test_compiler_generate`, up from 9), 84/84 full Python suite,
`mypy --strict` clean, `make conform` 20/20, and all 23 real GET operations
independently re-confirmed to still compile with the expected coverage
split (20 `representable`, 3 `representable_partial`, 0 unexpected
`not_representable`).

### Milestone 3c — Mock tests, assumptions, coverage decision

Deliverables
- Mock test generation for each compiled plan
- Assumption surfacing with source spans (`spec_claims`) for anything the
  spec left ambiguous
- Compile-time budget instrumentation

Test criteria
- [ ] ≥ 80% of the 20 operations execute correctly against mock on first
      generation attempt (no manual fixing)
- [ ] Every generated node carries ≥ 1 assumption with a resolvable source
      span where the spec was ambiguous (check against a spec known to have
      ≥ 1 ambiguity, don't just check the field is non-empty)
- [ ] Compile p50 < 3 min across the 20

Gate `make gate-3c`

### Phase 3 gate

`make gate-3` = `gate-3a` + `gate-3b` + `gate-3c`.

Exit when: `make gate-3` exits 0.

**Decision point after phase 3:** if `representable` is below 70% across the
sample, stop and reconsider the runtime before building further. Record the
decision in `CHANGELOG.md`. This decision point is not a milestone gate — it
is a judgement call the gates exist to inform, not replace.

---

## Phase 4 — Verification and evidence bundle

**Goal:** a reviewer can approve quickly and correctly.

### Milestone 4a — Sandbox execution and permission probe as a gate

Deliverables
- Sandbox execution against real credentials (5 nodes)
- Permission probe suite from milestone 2d wired in as a **blocking**
  verification stage — reuse it, do not reimplement it

Test criteria
- [ ] Sandbox verification passes for 5 phase-3 nodes against real sandbox
      accounts
- [ ] A node that follows a cross-host redirect (deliberately constructed
      test case) cannot pass this stage and therefore cannot be approved

Gate `make gate-4a`

### Milestone 4b — Evidence bundle

Deliverables
- Evidence bundle assembly: behaviour summary, exact request preview,
  redacted trace, test results, capability list, assumptions with citations
- `GET /nodes/{id}/versions/{v}/evidence` per `docs/API.md`

Test criteria
- [ ] Evidence bundle renders for every phase-3 node (20/20)
- [ ] Every field in the `docs/API.md` evidence schema is populated (no
      silently-omitted field) for at least one node used as a golden fixture

Gate `make gate-4b`

### Milestone 4c — Approval, signing, freeze

Deliverables
- `POST /nodes/{id}/versions/{v}/approve` → signed, immutable artifact
  (reuses phase-0 sign/verify)
- `ferrule node {verify,review,approve}` CLI commands
- Reviewer timing study (3 people, 5 nodes each)

Test criteria
- [ ] Approval produces a signed, immutable artifact
- [ ] A second approval attempt on the same version is rejected with `409`
- [ ] No code path allows mutating an approved `node_version` row except its
      `status` field (this is invariant 4 — check it against the actual
      schema/ORM layer, not just the API surface)
- [ ] Reviewer timing: 3 people unfamiliar with the API approve or reject 5
      nodes each; median review time recorded (no pass threshold at this
      gate — it is the baseline later phases are measured against)

Gate `make gate-4c`

### Phase 4 gate

`make gate-4` = `gate-4a` + `gate-4b` + `gate-4c`.

Exit when: `make gate-4` exits 0.

---

## Phase 5 — Durable execution

**Goal:** workflows run, resume, and stay pinned.

### Milestone 5a — Orchestrator state machine and journal

Deliverables
- Orchestrator state machine on Postgres
- Run journal, step traces
- Failure classification and routing per `SPEC.md` §7

Test criteria
- [ ] Each failure class (`transient`, `auth`, `schema_mismatch`,
      `permission_denied`, `timeout`, `rate_limited`) routes as specified (6
      cases)
- [ ] Retry with backoff and jitter behaves correctly for `transient` and
      `rate_limited` (honours `Retry-After` for the latter)

Gate `make gate-5a`

### Milestone 5b — Workflow pinning and multi-node chains

Deliverables
- 2–3 node chaining via API (no canvas)
- `POST /workflows/{id}/versions` with `artifact_hash`-only node references
  (reject slug references and unknown/unapproved hashes with `422`)

Test criteria
- [ ] A 3-node chain completes end to end against a live sandbox API
- [ ] A workflow pinned to `hash-A` does not switch when `hash-B` is approved
      for the same node — this is invariant 3, tested at the workflow-run
      level, not just the schema level
- [ ] `POST /workflows/{id}/versions` rejects a graph referencing a node by
      slug or an unapproved hash

Gate `make gate-5b`

### Milestone 5c — Resume, replay, exactly-once-logical delivery

Deliverables
- Crash recovery from the journal
- `POST /runs/{id}/steps/{seq}/replay` (`recorded_response` and `live` modes,
  with `live` rejected for non-`read_only` nodes — this anticipates phase 6's
  invariant 8 but must hold now since the endpoint ships now)

Test criteria
- [ ] `kill -9` on a worker mid-run: run resumes and completes, < 30 s
- [ ] Recorded-response replay of a single step is byte-deterministic
- [ ] At-least-once delivery does not duplicate: a forced retry of a
      read-only step produces one journal entry per attempt and one logical
      result
- [ ] `live` replay mode is rejected with `403` for any node whose
      `side_effect_profile` is not `read_only`

Gate `make gate-5c`

### Phase 5 gate

`make gate-5` = `gate-5a` + `gate-5b` + `gate-5c`.

Exit when: `make gate-5` exits 0.

---

## Phase 6 — Drift, learning mode

**Goal:** baselines accumulate without generating noise. **No alerting in
this phase — that's phase 7.**

### Milestone 6a — Fingerprinting

Deliverables
- Response fingerprinting at the proxy (field paths, types, nullability,
  array-ness, enum-ish value sets — never values)

Test criteria
- [ ] Fingerprints extracted from 1,000 synthetic responses with no value
      material persisted (automated scan, 0 hits)

Security criteria
- [ ] Fingerprint extraction code path has no branch that persists a raw
      field value under any condition (review the extractor function
      directly, not just its output on the 1,000-response sample)

Gate `make gate-6a`

### Milestone 6b — Baseline maturity states

Deliverables
- `drift_baselines` table and maturity states (`learning` → `baselined`)
- Maturity thresholds (distinct observations, distinct calling contexts)
- `GET /drift/baselines?node_version_hash=` per `docs/API.md`

Test criteria
- [ ] Baseline transitions `learning` → `baselined` only at threshold, not
      before (test both sides of the boundary)
- [ ] `detection_active` is `false` while `learning`, regardless of anomaly
      signal present in the underlying data

Gate `make gate-6b`

### Milestone 6c — False-positive corpus

Deliverables
- Known false-positive corpus: nullable fields appearing/disappearing,
  account-tier field variation, empty arrays during verification, legitimate
  new enum values, error-rate shifts from customer config rather than
  upstream change
- Severity scoping per `SPEC.md` §6.3 (mapped fields only)

Test criteria
- [ ] Known false-positive corpus produces **zero** would-be alerts when
      replayed (build the corpus before writing any detector logic against
      it — this is the real gate of the phase)
- [ ] Severity scoping verified: unmapped field changes classify `info`, not
      `critical`, on at least one case per corpus category

Gate `make gate-6c`
Build the corpus before the detector. If the detector is written first, this
gate tends to get quietly weakened to make it pass — don't let that happen.

### Phase 6 gate

`make gate-6` = `gate-6a` + `gate-6b` + `gate-6c`.

Exit when: `make gate-6` exits 0.

---

## Phase 7 — Drift detection and alerting

**Goal:** the differentiator works and is trustworthy.

### Milestone 7a — Shape diffing against mature baselines

Deliverables
- Shape diffing engine comparing new observations against a `baselined`
  node's fingerprint

Test criteria
- [ ] 10 injected real breaking changes (drawn from actual upstream API
      changelogs where possible, not synthetic) detected, each with correct
      severity per `SPEC.md` §6.3
- [ ] Phase 6's false-positive corpus still produces zero alerts when run
      against this milestone's diffing engine (regression check — do not let
      7a's detector reintroduce noise 6c eliminated)

Gate `make gate-7a`

### Milestone 7b — Confirmation ladder and blast radius

Deliverables
- Confirmation ladder: observe → confirm (multiple calls or safe read-only
  probe) → compute blast radius → alert, mark `at_risk`
- `GET /drift/observations` per `docs/API.md`, including `blast_radius`

Test criteria
- [ ] No `at_risk` marking occurs from a single observation (negative test —
      construct exactly one anomalous observation and assert no alert)
- [ ] Blast radius correctly lists every workflow version referencing the
      affected hash (construct a fixture with 3 workflow versions, 2
      referencing the affected hash, assert exactly those 2 are listed)

Gate `make gate-7b`

### Milestone 7c — Quarantine

Deliverables
- Quarantine transition, gated on high confidence **and** explicit workspace
  policy
- `POST /nodes/{id}/versions/{v}/quarantine`
- Fixture replay restriction to `read_only` nodes (invariant 8), enforced at
  this layer as well as in phase 5

Test criteria
- [ ] Quarantine blocks new runs; runs already in flight complete (a run
      never switches implementation mid-execution — re-verify this holds
      under quarantine specifically, not just under version pinning from 5b)
- [ ] Fixture replay refuses to run against a non-`read_only` node (`403`,
      matching milestone 5c's test but exercised here against the drift
      replay trigger path specifically)
- [ ] Quarantine without explicit workspace policy enabled does not occur
      even at high confidence (policy gate tested independently of
      confidence level)

Gate `make gate-7c`

### Phase 7 gate

`make gate-7` = `gate-7a` + `gate-7b` + `gate-7c`.

Exit when: `make gate-7` exits 0.

---

## Phase 8 — Prose documentation ingest

**Goal:** the actual wedge — private APIs without OpenAPI.

Deferred to last deliberately: it is the noisiest, most research-heavy stage,
and everything else must be proven first.

### Milestone 8a — Extraction and confidence gating

Deliverables
- Prose/PDF/Postman-collection ingest and candidate spec extraction
- Confidence scoring; low confidence requests more documentation rather than
  guessing

Test criteria
- [ ] 10 real private-API doc sets produce candidate specs
- [ ] Every extracted claim carries a resolvable source span
- [ ] A deliberately low-quality/incomplete doc set triggers a
      "request more documentation" response rather than a low-confidence
      guess presented as a normal result

Gate `make gate-8a`

### Milestone 8b — Compilation without manual editing

Deliverables
- Wiring extracted candidate specs into the phase-3 compiler pipeline
  unmodified (if phase 3's compiler needs changes to accept this input, that
  is itself a finding — record it, don't silently special-case prose input)

Test criteria
- [ ] ≥ 60% of operations from the 10 doc sets reach a compilable plan
      without manual spec editing

Gate `make gate-8b`

### Phase 8 gate

`make gate-8` = `gate-8a` + `gate-8b`.

Exit when: `make gate-8` exits 0.

---

## Parallel track — validation (optional, startup path only)

Not a build phase. Run only if pursuing this commercially. Not gated by
`make` commands — gated by recruiting real participants and recording real
data.

- Recruit 3–5 integration engineers
- Concierge-run the compiler on their real documentation
- **Record the form the documentation arrived in every time** — if most are
  PDFs and Postman collections, phase 8 moves to the front
- Measure: time from docs to approved integration; % approved with minor
  edits; incorrect assumptions per node; % representable without custom
  code; reviewer time; whether they would run it in production; whether
  drift monitoring is worth paying for

**The metric that matters:** what percentage of real integrations are
representable by the plan **and** approved faster than the same engineer
would build them with a coding agent. Not generation accuracy alone.

Kill criteria
- Prospects praise the idea but will not supply a real integration case
- Reviewers ignore the evidence and rewrite nodes by hand
- Representable rate below 70%
- Drift repair is indistinguishable from regeneration
