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
| 2 — Proxy & broker | 2a ✅ / 2b ✅ / 2c–2d ⬜ | in progress |
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
`invalid_rendered_request`.
Exit when: comparison/host/redirect/budget/size/content-type denial tests
pass and the injection probe holds. — met.

This is the single highest-priority gate in the project. Do not let CI treat
it as advisory — a red `gate-2b` blocks everything downstream of phase 2.

### Milestone 2c — Credential broker and injection

Deliverables
- Credential store with `broker_ref` indirection (`services/policy` or a
  dedicated broker component — value never lands in Postgres)
- Secret resolution: `{{ secret.NAME }}` markers substituted only inside the
  proxy, immediately before the outbound call
- Redacted capture of request/response for trace and drift, with stripping of
  secret material from the response before it is returned to the worker

Test criteria
- [ ] Secret marker in a plan template resolves correctly to the bound
      credential's value inside the proxy
- [ ] The value passed to `POST /credentials` is never returned by any
      endpoint or present in any log line (automated scan over API responses
      and structured logs, 0 hits)
- [ ] **No credential material appears in any worker-visible surface**:
      worker memory dump, worker logs, trace blobs, error messages returned
      to the worker (automated scan, 0 hits) — this is the load-bearing test
      for invariant 1 in `CLAUDE.md`/`AGENTS.md`
- [ ] Deleting a credential (`DELETE /credentials/{id}`) causes the next run
      bound to it to fail with failure class `auth`, not a generic error

Security criteria
- [ ] Redaction happens before the trace/log write, not as a post-processing
      pass over already-written data (grep for any "redact after write" or
      cleanup-job pattern — this is invariant 6 and it is checked here, not
      assumed)

Gate `make gate-2c`

### Milestone 2d — Adversarial verification suite

Deliverables
- Permission probe suite as a standalone, repeatable adversarial test harness
  (this becomes the phase-4 verification stage later — build it once, reuse
  it)
- Latency benchmark harness (local mock, controllable rps)

Test criteria
- [ ] Permission probe suite runs all of 2b's and 2c's denial/injection cases
      against a running proxy instance as black-box HTTP tests, not unit
      tests against internal functions
- [ ] p95 added latency < 25 ms under 50 rps against a local mock

Gate `make gate-2d` / `make security`
`make security` is the permission probe suite referenced by
`CLAUDE.md`/`AGENTS.md` as required before any completion claim from this
point forward in the project — not just for phase 2.

### Phase 2 gate

`make gate-2` = `gate-2a` + `gate-2b` + `gate-2c` + `gate-2d`.

Exit when: `make gate-2` exits 0 **and** `make security` exits 0.

---

## Phase 3 — Compiler, OpenAPI path

**Goal:** generation accuracy on real specs.

### Milestone 3a — Ingest and operation resolution

Deliverables
- OpenAPI ingest (parse, validate, hash source documents)
- Operation resolution from a natural-language task description to a
  candidate operation (or `needs_input` when ambiguous)
- `POST /sources`, `POST /sources/{id}/documents`,
  `POST /sources/{id}/extract` from `docs/API.md`

Test criteria
- [ ] 8 public OpenAPI specs ingest without error and produce a queryable
      operation list
- [ ] A deliberately ambiguous task description against a spec with two
      matching operations returns `needs_input` with both candidates, not a
      guess
- [ ] `POST /jobs/{id}/resume` with a chosen operation ID proceeds correctly

Gate `make gate-3a`

### Milestone 3b — Schema and plan generation

Deliverables
- Input/output port schema generation
- Plan generation targeting the phase-1 plan language, with a bounded
  regenerate-on-failure loop (static check failure feeds back into
  generation, bounded attempts, then surfaces to a human)
- `plan_coverage` verdict recorded for every attempt, success or failure

Test criteria
- [ ] 20 GET operations across the 8 specs from 3a compile to plans that pass
      the phase-1 static checker
- [ ] `plan_coverage` recorded for all 20, including any that fail to compile
- [ ] 100% of the 20 either produce a valid plan or an explicit
      `not_representable` verdict — never a silently wrong plan that passes
      static checks (this is checked by manual inspection of a sample, not
      just automated — record the sample size and reviewer)

Security criteria
- [ ] Generated plans are static-checked (milestone 1a's checker) before
      being persisted as a `node_version` row in any status other than
      `draft` — generation cannot skip the checker via a different code path

Gate `make gate-3b`

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
