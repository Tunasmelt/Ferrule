# Changelog

Format: [Keep a Changelog](https://keepachangelog.com/). Versions here refer to
**specification** versions until code ships, then to releases.

---

## [Unreleased] — Process

### Milestone 4a audit: stale test-cache finding fixed (2026-09-19)

Found by re-running gate-4a twice rather than trusting one green run:
`go test` was caching the live sandbox test's result, so a second
`make gate-4a` run with no source changes silently replayed a stale PASS
with **zero live network traffic** -- confirmed directly (instant
`(cached)`, no real requests). This would have defeated milestone 4a's
entire purpose (catching real-world drift, exactly as it already did once
for the Open-Meteo bug) on every run after the first. Fixed with
`-count=1` on both gate-4a invocations.

While diagnosing, checked whether milestone 2d's FERRULE_LATENCY_BENCHMARK
precedent -- the pattern 4a copied -- had the same gap. It did, unnoticed
since 2d closed: a repeat `make gate-2d` would equally have replayed a
stale cached p95 instead of re-measuring. Fixed there too. Both gates
re-verified to genuinely re-execute on repeat runs now.

Also reviewed and confirmed correct: Codex's own probe.go fix (disabling
JSON's default HTML-escaping of `&` in the shared probe request encoder,
since the proxy's own canonical renderer never escapes it) is real, well
-scoped, and hadn't caused any prior failures only because no existing
probe fixture used such a character.

### Milestone 4a closed: sandbox execution against real APIs (2026-09-19)

Phase 4 begins. Scope decision made with the user first: "sandbox
execution against real credentials" was narrowed to no-auth-only public
APIs (PokeAPI, JSONPlaceholder, Open-Meteo) rather than a real GitHub/
Stripe-style credential, since the user chose not to hand over a token for
this milestone. Proving the proxy's credential-injection path against a
live (not mocked) API remains open for later.

New services/proxy/sandbox_test.go drives 5 real phase-3-shaped nodes
through the real POST /v1/authorize endpoint with the real HTTP transport
-- genuine live internet calls, no mocking. Milestone 2d's permission
probe suite runs first as a blocking pre-condition (reused, not
reimplemented), and one deliberately malicious cross-host-redirect node
runs through the identical verification code path as the 5 real ones,
proving the verification *stage* itself rejects it. FERRULE_SANDBOX_LIVE=1
-gated, following 2d's own established pattern for live/timing tests, so
it never runs under `make check` by default.

Doing this for real, not mocked, caught a genuine bug immediately:
open-meteo.json's searchGeocoding operation had a factually wrong host
baked into it since milestone 3a (api.open-meteo.com/v1/geocoding 404s for
real; the actual API lives on geocoding-api.open-meteo.com/v1/search).
Every prior test of this operation across milestones 3a-3c used a mock
transport and never caught it. Fixed the fixture and swapped the sandbox
test's 5th node to getElevation (confirmed correctly hosted). This is
exactly the failure mode "sandbox execution against real APIs" exists to
catch, on its first real run.

Built by Codex (pure Go, no credentials); Codex's own sandbox had no
outbound network access and said so explicitly rather than papering over
it. Claude Code independently re-ran the live gate with real network
access, which is what surfaced the Open-Meteo bug. gate-4a exits 0 (5/5
real nodes pass, malicious node correctly rejected); make check (96/96)
and make conform (20/20) unaffected. See PHASES.md milestone 4a for full
detail.

### Whole-Phase-3 audit: 3 findings fixed (2026-09-19)

Audited by actually driving the full pipeline (ingest -> resolve ->
generate -> mock-verify -> claims) through the real HTTP API end-to-end,
since no prior test had: every 3a test stayed at the HTTP/store layer,
every 3b/3c test loaded fixtures from disk directly and called internal
functions, bypassing the API layer entirely. The three milestones had
never been proven to compose.

They didn't, cleanly. Fixed 3 issues, each reproduced directly before
fixing, not just reasoned about:
- No adapter existed between the API's JSON operation shape and the
  internal Operation/Parameter dataclasses generate.py/claims.py require.
  `Operation(**response_json)` looks like it works (dataclasses don't
  validate field types) but crashes with a confusing AttributeError deep
  inside compile_operation. Fixed with openapi.operation_from_mapping.
- Source.base_url (required by every compile) was never retrievable
  through the API -- not even echoed back on creation. Fixed: SourceResponse
  now includes it, plus a new GET /sources/{id}.
- Uploaded document bytes (required by claims.extract_claims) couldn't be
  retrieved after upload. Fixed: new GET /sources/{id}/documents/{id},
  with a same-source ownership check.

New tests/test_compiler_pipeline.py proves the full pipeline composes
through the real API using only data a real caller could retrieve, and
that the result is byte-identical to compiling directly from ingest() --
the API boundary is provably lossless. gate-3 exits 0 (40 tests); 96/96
full suite; mypy --strict clean; make conform unaffected. See PHASES.md's
Phase 3 gate section for full detail.

### Milestone 3c closed; Phase 3 gate closed; decision point recorded (2026-09-19)

New `services/compiler/python/ferrule_compiler` modules: `mocktest.py`
(executes a compiled plan through 1c's real, unmodified interpreter
against an in-process canned transport, synthesizing input from the
compile's input_schema -- no sockets, no fixture files), `claims.py`
(surfaces `spec_claims` per API.md with source spans resolved to real
anchor text in the raw document bytes via a small brace-balanced scanner,
not fabricated offsets), and `budget.py` (reusable compile-time timing).

Real measured numbers: 23/23 (100%) of real GET operations pass mock
execution on first attempt (bar was 80%); compile p50 is ~1ms across 23
operations (bar was 3 minutes, expected to clear it easily since
generation is deterministic and in-process); every compiled operation
carries >=1 resolvable-source-span claim, verified against a known-
ambiguous operation (github's issues/list-for-repo) with 2 independent
span-resolution checks.

**Phase 3 gate closed.** Decision point per SPEC.md section 3.4: 20/23
(87%) of this phase's compiled GET operations are `representable`, clearing
the >=70% bar. Caveat recorded rather than overclaimed: the sample is
GET-only by milestone 3b's own scope decision -- non-GET operations aren't
represented in it at all, so this is a positive early signal for the
URL/query/header mapping slice specifically, not yet a verdict on request
bodies or write operations. Continuing to build; revisit this number once
a future milestone compiles operations with request bodies.

### Milestone 3b audit: 2 findings fixed (2026-09-19)

Whole-milestone audit found and fixed 2 issues by tracing how
`generate.py`'s URL construction interacts with `openapi.py`'s parameter
parsing and the checker's double-brace-only template grammar:
- An undeclared or case-mismatched path placeholder (e.g. spec path
  `/widgets/{ID}` with declared parameter `id`) would silently leave a
  literal, unsubstituted segment in the generated URL -- passing all
  static checks while being wrong at request time. Fixed by validating the
  raw path's placeholders against declared parameter names before
  substitution. (First fix attempt scanned the substituted string instead
  and incorrectly flagged legitimate `{{ input.x }}` markers as stray
  placeholders, breaking 3 tests -- caught immediately by re-running the
  suite, corrected before considering the fix done.)
- A path parameter and a query parameter sharing the same name would
  silently collapse onto one shared `input.<name>` variable. Fixed by
  rejecting cross-location name collisions as `not_representable`.

Neither was triggered by the 23 real fixture operations; both are now
covered by regression tests. 28/28 gate-3b tests pass (up from 25), 84/84
full suite, mypy --strict clean, make conform unaffected.

### Milestone 3b closed: deterministic schema and plan generation (2026-09-19)

Scope decision made with the user before writing code: plan generation is
deterministic template mapping (path/query/header parameters -> plan
templates), not an LLM-backed "Builder model" as SPEC.md §8 eventually
intends -- 3b's actual test criteria (20+ real GET operations, no bodies)
don't need one, and a real LLM integration is a provider/cost decision to
raise separately when a later milestone actually requires it.

New `services/compiler/python/ferrule_compiler/generate.py`: maps a GET
`Operation` (extended in 3a's `openapi.py` with a new `Parameter` field)
onto a phase-1 plan, input_schema, and output_schema, reusing 1c's
`ferrule_interpreter.coverage.classify_plan` for the `plan_coverage`
verdict. Fixtures extended from 13 to 23 real GET operations across the
same 8 specs, plus one new synthetic fixture to honestly exercise the
`not_representable` path (a cookie-location parameter). All 5 first-party
Python packages are now genuinely `pip install -e .`-editable-installed
(with `py.typed` markers) rather than resolved only via test-file
`sys.path` hacks, since generation is the first application code needing a
real cross-package import. See `PHASES.md` milestone 3b for full detail,
including the manual-inspection record its test criteria require.

### Milestone 3a audit: 3 findings fixed (2026-09-19)

Whole-milestone audit of 3a (cross-file/integration issues a narrow
per-file review wouldn't catch), all 3 findings fixed immediately:
- Unbounded document upload combined with `yaml.safe_load`'s exposure to
  anchor/alias resource-exhaustion (same class as Phase 2's already-fixed
  unbounded-request-body finding) — fixed with a 10 MiB upload cap.
- Check-then-act race in job resume: two concurrent resumes of the same
  `needs_input` job could both pass validation before either wrote,
  silently double-resuming (same class as Phase 2's SecretBindings race) —
  fixed with `Store.resume_needs_input` holding one lock across the whole
  check-select-write sequence; verified with a threaded regression test.
- Fallback `operation_id` collisions for structurally different paths that
  tokenize identically (e.g. `/foo/bar` vs `/foo-bar`) could make a resume
  silently resolve to the wrong operation — fixed with deterministic
  collision disambiguation. See `PHASES.md` milestone 3a for full detail.

### Milestone 3a closed: compiler ingest and operation resolution (2026-09-19)

Phase 3 (the compiler) begins. New `services/compiler/python/ferrule_compiler`
package: dependency-light OpenAPI 3.x ingest with sha256 source hashing,
a deterministic Jaccard-similarity operation resolver (no LLM call — that's
milestone 3b's concern), an in-memory mutex-guarded store, and a FastAPI
surface implementing `POST /sources`, `POST /sources/{id}/documents`,
`POST /sources/{id}/extract` from `docs/API.md`, plus two documented
additions beyond API.md's surface (`GET /sources/{id}/operations`,
`POST /sources/{id}/resolve`) and `POST /jobs/{id}/resume`. 8 new hand-authored
OpenAPI fixtures under `tests/fixtures/openapi/` (GitHub, Stripe, PokeAPI,
JSONPlaceholder, Open-Meteo, Slack, SendGrid, Twilio). See `PHASES.md`
milestone 3a for full detail and verification notes.

### All 5 tracked whole-phase audit findings fixed (2026-09-19)

The whole-phase audit below left 5 findings tracked but unfixed. All 5
are now fixed, at the user's request.

**High — FIXED**
- ~~Authorization was fully replayable~~ -- `JournalEntry` gained a
  `Consumed` flag; `Authorize` denies (`replay_denied`) any further
  authorization of an entry that already delivered one complete response.
  CLAUDE.md's existing append-only-journal invariant means a legitimate
  retry is expected under a *new* `step_seq`, so this doesn't block
  retries. `server.go` marks consumed immediately before writing the
  successful response. `TestServerDeniesReplayOfCompletedRequest` added.

**Medium — FIXED**
- ~~`POST /v1/authorize` had no authentication~~ -- added a shared-secret
  bearer check (`Server.AuthToken`, constant-time compared), failing
  closed when unset. `TestServerRequiresAuthentication` added.
- ~~`SecretBindings` was an unsynchronized plain map~~ -- converted to a
  mutex-guarded struct (`NewSecretBindings`/`Bind`), matching the other
  three stores. `TestSecretBindingsConcurrentAccessDoesNotPanic` added.
- ~~`ForwardPolicy` never read a signed artifact's own `runtime_limits`~~
  -- `Authorize` now parses an optional top-level `runtime_limits` block
  onto `Decision.ArtifactLimits`; new `MergeForwardPolicy` combines it
  with the caller's policy, always taking the more restrictive value --
  the artifact can tighten its effective policy, never widen it.
  `TestServerEnforcesArtifactRuntimeLimitsOverServerPolicy` drives a real
  HTTP round trip proving the artifact's tighter limit wins.

**Low — FIXED**
- ~~Failure classification (SPEC.md §7) was incomplete~~ -- `SecurityEvent`
  gained a `FailureClass` field (`"permission_denied"` for every denial
  in this package); a new `TransportError` type classifies network
  failures as `"timeout"` or `"transient"`, computed from the original
  error (via `net.Error.Timeout()`) before redaction discards its type
  information. Internal, effectively-unreachable proxy faults (decode
  failures, nil transport, invalid URLs) deliberately stay unclassified
  rather than mislabeled.

Fixing replay protection required restructuring two `probe.go` cases
(injection, deleted-credential) that resubmitted the same `(run_id,
step_seq)` twice -- now each registers its own fresh journal entry,
matching what two independent workflow runs would actually do -- plus a
`"_probe_name"` manifest discriminator so same-upstream fixtures stop
colliding on `ArtifactCache.Push`'s immutability check. The latency
benchmark now pre-registers 150 distinct entries instead of resending one
request 150 times (p95 unaffected, still comfortably under 25 ms).

`go vet`, `gofmt`, full `go test ./...`, `gate-2a`/`2b`/`2c`/`2d`, `make
security`, `make check`, `make conform` all green, no regressions.

### Whole-phase Phase 2 audit (2026-09-19) — 2 fixed, 5 tracked

Every prior 2a/2b/2c/2d audit was scoped to its own milestone's files.
This one deliberately looked across all of `services/proxy` together.
Claude Code independent pass, then a second, independent, read-only
Codex pass with no visibility into the first pass's findings -- Codex
found the most serious issue.

**High — FIXED**
- ~~`MemoryRunJournal` was keyed only by `(run_id, step_seq)`, with no
  binding to which artifact or step a journal entry was recorded for~~ --
  reproduced directly: a destructive step in one signed artifact was
  fully authorized using a read-only step's journal entry from a
  completely different artifact, sharing only `run_id`/`step_seq`/digest.
  A real confused-deputy gap in the core request-binding guarantee.
  Fixed: `JournalEntry` now carries `NodeVersionHash`/`StepID`, and
  `Authorize` rejects a mismatch (`journal_step_mismatch`) before the
  digest check. `TestAuthorizeRejectsJournalEntryFromWrongArtifactAndStep`
  added.

**Low — FIXED**
- ~~`/v1/authorize` read its request body with an unbounded
  `json.Decoder`~~ -- an unauthenticated client could send an
  arbitrarily large body before decode failure. Fixed with
  `http.MaxBytesReader` (1 MiB). `TestServerRejectsOversizedRequestBodyOverHTTP`
  added.

**Tracked, not fixed in this audit:**
- **High**: authorization is fully replayable -- no single-use marker,
  fresh redirect/request budget on every HTTP call. Needs Phase 5's
  run-state-machine to do correctly (naive single-use marking would
  break legitimate retries of transiently-failed steps).
- **Medium**: `POST /v1/authorize` has no caller authentication. Traced
  concretely: a network-only attacker can't forge an accepted request
  from nothing (needs an exact `step_input_digest`, which requires
  journal visibility), but identifiers here function as a de facto
  bearer capability, and combined with the replay finding, one observed
  request becomes indefinitely reusable. Safe today only under an
  external network-isolation assumption the HTTP contract doesn't
  represent.
- **Medium**: `SecretBindings` is a plain unsynchronized map, unlike the
  three other stores which all use a mutex -- a real Go data race once
  any future credential-rebind/rotation path runs concurrently with live
  traffic. No live trigger today; flagged for whoever adds one.
- **Medium**: `ForwardPolicy` is process-wide and caller-supplied, never
  derived from a signed artifact's own `runtime_limits` (SPEC.md §5) --
  not a shape bug, just nothing reads it, because no schema in this repo
  defines it yet.
- **Low**: failure classification (SPEC.md §7) is incomplete across most
  Authorize-side denials and generic transport errors; a minor status
  inconsistency between two effectively-unreachable internal failure
  paths (`invalid_rendered_request` vs. a `decodeOutboundRequest`
  failure).

`go vet`, `gofmt`, full `go test ./...`, `gate-2a`/`2b`/`2c`/`2d`, `make
security`, `make check`, `make conform` all green, no regressions.

### Latency test isolated from unrelated gates (2026-09-18)

`/code-review` flagged: `TestProxyLatencyP95Under50RPS` is a real
wall-clock assertion (flaky on a loaded/shared machine through no fault
of the proxy code), and since `gate-2a`/`gate-2b`/`gate-2c` all run the
same unfiltered `go test ./services/proxy/...` (there's no per-milestone
test binary split), it was silently running -- and could fail -- under
all three, not just `gate-2d`. Fixed: the test now skips by default,
opting in only via `FERRULE_LATENCY_BENCHMARK=1`, set only by `gate-2d`.
Confirmed via `-v`: `SKIP` (0.00s) under a plain `go test`, runs for real
under `gate-2d`. `go vet`, `gofmt`, full `go test ./...`, `make check`,
`make conform` all still green.

### Phase 2 milestone 2d — Adversarial verification suite (2026-09-18)

**Phase 2 is now fully closed.** Built by Codex via `codex-task.mjs` in
two bounded dispatches, each independently verified.

Dispatch 1: `services/proxy/http_transport.go` (the project's first real
`net/http` `Transport`, with automatic redirects disabled via
`CheckRedirect` so `Forward`'s own redirect policy from milestone 2b
actually runs against real HTTP responses instead of being silently
bypassed by the client) and `server.go` (the project's first real HTTP
server, `POST /v1/authorize`, wrapping `Authorize`+`Forward` -- it calls
`Authorize` itself and passes its exact `Decision` straight to `Forward`,
never constructing one, since it couldn't set the unexported `verified`
field anyway).

**Caught during review, fixed before dispatch 2:** `server.go` copied the
upstream's `Content-Length` header through unchanged, but `Forward`'s
redaction can change `response.Body`'s length relative to what the
upstream declared. Reproduced in complete isolation from this codebase:
writing a body whose real length differs from a copied, stale, smaller
`Content-Length` makes Go's own `net/http` client read zero bytes for the
ENTIRE response and report `"unexpected EOF"` -- not a graceful
truncation. Fixed by omitting `Content-Length`/`Transfer-Encoding` from
the copied headers and letting `net/http` compute the correct one.
`TestServerOmitsStaleContentLengthAfterRedaction` added.

Dispatch 2: `probe.go` (`RunPermissionProbes`, an exported, reusable
black-box HTTP harness covering all 12 of 2b's and 2c's denial/injection
cases against a real running server with a real transport -- this becomes
phase 4's verification stage, built once), `latency_test.go` (p95 ≈
530-570 µs over 150 requests at 50 rps, comfortably under the 25 ms bar),
and a real `make security` target.

Codex correctly found and honestly reported two real gaps at the
HTTP-surface boundary rather than working around them out of its
authorized scope (it was told not to touch `forward.go`/`server.go` for
that dispatch):
- A real `Transport` enforcing the response-size bound returned a plain
  untyped error on overflow, which `Forward` passed through as a generic
  error instead of a `response_too_large` `SecurityEvent` -- the
  mock-transport unit tests never caught this since mocks just returned
  an oversized value directly. Fixed with a new typed
  `ResponseTooLargeError`.
- `ResolveSecrets`' `*FailureClassError` (`"auth"` on a deleted
  credential) was discarded into the same generic message as any other
  `Forward` error. Fixed in `server.go`: recognizes `*FailureClassError`,
  responds `403` with a `failure_class` field.

All 12 permission probes pass; `gate-2d`, `gate-2c`, `gate-2b`, `gate-2a`,
`gate-2` (new aggregate Makefile target), `make security`, `make check`,
`make conform` all green.

### Milestone 2c's last tracked item, fixed (2026-09-18)

- ~~`Forward` trusted only the exported `decision.ChecksPassed` boolean,
  letting any caller forge `Decision{ChecksPassed: true, ...}` and obtain
  secret resolution/forwarding with no real `Authorize` call~~ — fixed
  using Go's package-visibility boundary instead of a runtime token:
  `Decision` gained an unexported `verified` field only `Authorize`'s
  success path sets; `Forward` now requires it. A caller outside
  `package proxy` cannot set an unexported field at all (compile error),
  so the only way to produce a `Decision` `Forward` will honor is a real,
  successful `Authorize` call. `TestForwardRejectsChecksPassedWithoutAuthorize`
  added. `go vet`, `gofmt`, full `go test ./...`, `gate-2c`, `gate-2b`,
  `gate-2a`, `make check`, `make conform` all green, no regressions.

### Milestone 2c dedicated audit (2026-09-18) — 3 fixed, 1 tracked

Requested given 2c is the first code in this project to hold a real
secret value. Claude Code independent pass, then a second, independent,
read-only Codex pass with no visibility into the first pass's findings.

**Medium — FIXED (found by Claude Code)**
- ~~`CredentialStore` had no `String()`/`GoString()` method~~ — Go's
  `fmt` prints unexported fields under `%v`/`%+v`/`%#v` via reflection;
  confirmed `fmt.Sprintf("%+v", store)` dumped every stored credential.
  Fixed: both methods now return only a count.
  `TestCredentialStoreFormattingDoesNotLeakValues` added.

**High — FIXED (found by both passes independently; Codex reproduced it
first, concretely)**
- ~~`Redact` only matched a secret's exact raw bytes, missing a
  JSON-string-re-escaped echo~~ (`"` → `\"` when an upstream reflects the
  credential inside its own JSON response) — reproduced directly. Fixed
  with a deliberately bounded partial mitigation (URL-encoding, base64,
  and other transformations remain unbounded and are not chased):
  `Redact` also searches for each secret's JSON-string-escaped form,
  using the same escaper `ResolveSecrets` already uses to embed values.

**High — FIXED (found by Codex, independently reproduced by Claude Code)**
- ~~`SecurityEvent.Reason` for the post-resolution denial paths
  (cross-host redirect, budget, response-too-large, disallowed
  content-type) embedded upstream-controlled response metadata without
  redaction~~ — reproduced directly and concretely: an upstream setting
  its `Content-Type` header to literally be the resolved secret caused
  `SecurityEvent.Reason` to contain the raw secret verbatim. Fixed:
  `forwardDenied` now redacts `reason` before building the event.
- ~~A transport error was returned verbatim after the transport received
  the resolved (secret-bearing) request~~ (Medium: real HTTP client
  errors commonly echo request details) — fixed: the error's text is
  redacted before `Forward` returns it.
- `TestForwardRedactsSecretFromDenialReason`,
  `TestForwardRedactsSecretFromTransportError` added.

**Tracked, not fixed (Medium today, would become High if exposed as-is)**
- `Forward` trusts only `decision.ChecksPassed`, with nothing
  structurally tying a `Decision` to a real `Authorize()` call — the same
  API-coupling class fixed for `Forward`/`AuthorizationRequest` in
  milestone 2b's audit, now reintroduced around secret resolution
  specifically. Left tracked because fixing it well means deciding how
  `Authorize` and `Forward` get bound together, which milestone 2d's
  black-box permission-probe suite will have to resolve anyway once it
  needs a real running proxy to test against.

`go vet`, `gofmt`, full `go test ./...`, `gate-2c`, `gate-2b`, `gate-2a`,
`make check`, `make conform` all re-run green, no regressions.

### Phase 2 milestone 2c — Credential broker and injection (2026-09-18)

Built by Codex via `codex-task.mjs`: `services/proxy/credentials.go`
(in-memory `CredentialStore`, no exported raw-value accessor),
`secrets.go` (`ResolveSecrets`, matching `{{ secret.NAME }}` markers with
render.go's own marker regex and substituting them only after
`Authorize` has already succeeded on the unresolved placeholder form;
`FailureClassError{Class: "auth"}` for a missing/deleted credential), and
`redact.go` (`Redact`, longest-value-first so a shorter secret can't
leave a fragment of a longer one exposed). `forward.go` wired minimally:
resolve after authorization succeeds, redact the response body and every
header before returning it. `authorize.go` and `render.go` were not
touched -- the byte-for-byte comparison that proves a worker's request
matches the plan still runs entirely on the unresolved placeholder text.

**Caught during independent review**: `ResolveSecrets` used
`strconv.Quote` (Go string-literal escaping) to embed a resolved secret
into the JSON envelope, instead of JSON escaping. Reproduced directly:
`strconv.Quote` on a value containing a bell character (`0x07`) produces
`\a`, which is not a valid JSON escape -- the resulting envelope failed
`json.Unmarshal` inside `Forward`, meaning any run using a credential
containing such a byte would fail outright with a decode error. Fixed by
reusing `render.go`'s existing `writePythonString` (the same JSON-safe
escaping already used everywhere else in this package) instead of
`strconv.Quote`. Added `TestResolveSecretsEscapesControlByteAsValidJSON`.

Two of milestone 2c's test criteria (the `POST /credentials` log-scan and
the trace/log redaction-timing check) are recorded as "met by scope, not
by a working scan" in `PHASES.md`: there is no HTTP server, structured
logging, or trace-capture system anywhere in this codebase yet for either
criterion to meaningfully scan. What's actually built and tested instead:
`CredentialStore` has no method that returns a raw value at all, and
`Forward`'s redaction runs inline before any response value is returned,
with no separate persistence step to grep for a "redact after write"
pattern in. Revisit both boxes for real once an HTTP/log layer exists.

`gate-2c` (added to the Makefile), `gate-2b`, `gate-2a`, `make check`,
`make conform` all re-run green, no regressions.

### Milestone 2b audit follow-ups (2026-09-18) — both tracked items fixed

The two items left tracked-but-not-fixed in the 2b dedicated audit
(below) were both fixed the same day at the user's request.

- ~~`packages/plan-schema` had no duplicate-step-`id` constraint~~ — fixed
  in `checker.py`: `check()` now walks `steps` once up front and emits
  `DUPLICATE_STEP_ID` (path `$.steps[N].id`) the first time an `id`
  repeats, the same shape as 0a's existing duplicate-object-key
  rejection. New fixture `tests/fixtures/plans/invalid/duplicate-step-id.json`
  and a case in `test_invalid_fixtures_have_expected_finding`. Full
  `python -m unittest discover` (56 tests) still green, no regression on
  0a–1c.
- ~~`Forward`'s response-size check only compared length after the
  transport had already buffered the full body~~ — fixed by changing
  `Transport`'s signature to accept `maxResponseBytes int` (`Forward`
  passes `policy.MaxResponseBytes` on every call), plus a new
  `BoundedRead(io.Reader, int) ([]byte, error)` helper any real transport
  should call instead of `io.ReadAll` -- reads one byte past the limit to
  detect an oversized source without needing its total length up front,
  the same technique `packages/interpreter/python/ferrule_interpreter/
  interpreter.py`'s `_http()` already uses. `Forward`'s own post-hoc
  length check stays as defense-in-depth for a transport that ignores the
  contract. This doesn't build a real `net/http` transport (still a later
  milestone's job) but gives it a tested, correct contract and helper to
  use. `TestBoundedReadRefusesOversizedSource`,
  `TestForwardPassesResponseByteLimitToTransport` added; updated every
  mock `Transport` in `forward_test.go` to the new signature.

`gate-2b`, `gate-2a`, `make check`, `make conform` all re-run green.

### Milestone 2b dedicated audit (2026-09-18) — 2 fixed, 2 tracked

Claude Code independent read pass, then a second independent read-only
Codex pass with no visibility into the first pass's findings; both
converged on the same two real issues.

**Medium — FIXED**
- ~~`Forward` took a `Decision` and a separate `AuthorizationRequest`
  parameter with nothing tying them together~~ -- a caller could
  authorize step A and then call `Forward` with A's `Decision` paired
  with step B's `AuthorizationRequest`, sending A's rendered request
  while attributing any `SecurityEvent` to B's identifiers. Not presently
  reachable (no orchestrator/caller exists yet to misuse it this way),
  but a real gap in the API contract the next milestone would otherwise
  build on. Fixed by moving `NodeVersionHash`/`RunID`/`StepSeq`/`StepID`
  onto `Decision` itself (populated once, by `Authorize`) and dropping
  `Forward`'s second parameter -- there is no longer a second identity
  value that could disagree with the `Decision`. Updated all call sites
  in `authorize.go`, `forward.go`, and `forward_test.go`.

**Low — FIXED**
- ~~`TestAuthorizeAcceptsBarePlanDocumentShape` submitted a stub request
  that fails the byte comparison and asserted only `StepFound`~~ --
  misleading coverage: the name implied full acceptance but it never
  proved that. Renamed to `TestFindStepAcceptsBarePlanDocumentShape`,
  with a comment pointing at `TestAuthorizeAcceptsMatchingRequest` (same
  bare-plan shape, already proves full acceptance).

**Tracked as follow-ups, not fixed in this audit:**
- Medium correctness / Low current security impact: `packages/plan-schema`
  has no uniqueness constraint on step `id` (neither the JSON Schema nor
  the Python checker), so a schema-valid plan can have two steps sharing
  an `id`; `findStep` always returns the first match, so the second
  occurrence can never be authorized (fails closed, not a bypass). This
  is a milestone 1a gap -- fixing it means adding a duplicate-`id` check
  to the checker (same shape as 0a's existing duplicate-object-key
  rejection) as its own scoped follow-up, not a change bundled into this
  audit.
- Medium for whichever milestone adds a real transport, no current
  exploit: `Forward`'s response-size check only compares length after a
  `Transport` has already returned a fully-buffered body. Fine against
  today's mock transports; a real `net/http`-backed transport will need
  to enforce the limit while reading, not after, or an oversized response
  becomes a memory/bandwidth exhaustion vector before the denial fires.

Re-verified against a fresh `gate-2b`, `gate-2a`, `make check`, `make
conform` -- all green, no regressions.

### Phase 2 milestone 2b — Request comparison and denial paths (2026-09-18)

Built by Codex via `codex-task.mjs` in two bounded dispatches, each
independently verified: (1) `Authorize()` now compares the independently
rendered request against the worker's submitted `canonicalized_request`
byte-for-byte and denies on any divergence, plus a host-declaration check
proving the plan's own `hosts` list -- not any broader capability-manifest
field -- is the sole authorization source; both denials emit a typed
`SecurityEvent`. (2) `services/proxy/forward.go` sends the authorized
request via a pluggable `Transport`, follows same-host redirects under an
explicit, precisely-defined budget, denies cross-host redirects without
ever fetching the target, and enforces a response-size limit and
content-type allowlist -- all decided from status/headers/length only,
proven never from response body text via a dedicated injection-probe test.

Codex correctly refused to touch `proxy_test.go` when it was out of scope
for the first dispatch, even though two of its fixtures predated
comparison enforcement (a stub submitted request, a manifest with no
declared hosts) and would now fail. Updated those fixtures directly
afterward to declare hosts and submit requests that actually match the
plan step's rendering, rather than weakening the new checks to
accommodate stale test data.

**Two more issues caught during a full-Go-codebase review pass after both
dispatches landed** (requested separately, scoped to "check for code
errors in all the Go architecture," not a fix task) **-- fixed directly,
not by Codex:**
- ~~The cross-host redirect check in `forward.go` compared `Hostname()`
  only~~ -- reproduced directly: an `https://api.example.com/...` to
  `http://api.example.com/...` redirect (identical hostname, downgraded
  scheme) was followed without denial. This is a live credential-leak
  vector the moment milestone 2c injects real secrets into forwarded
  headers -- an attacker-controlled redirect to the same host over
  plaintext would carry them along. Fixed by comparing the full origin
  (scheme + host) instead of hostname alone; added
  `TestForwardDeniesSchemeDowngradeRedirect`.
- ~~A JSON-decode failure on the independently-rendered request was
  mislabeled with `SecurityEvent.Code == "undeclared_host"`~~ -- that
  failure has nothing to do with hosts; mislabeling it would have caused
  later drift/alerting tooling to miscount an internal rendering fault as
  a host-authorization violation. Given its own code,
  `invalid_rendered_request`. Also removed an unnecessary variable-shadow
  of `err` in the same function while fixing this.

All fixes re-verified against `go vet`, `gofmt`, `go build` (clean across
every Go package in the repo), a fresh `gate-2a`, the new `gate-2b`,
`make check`, and `make conform` -- all green, no regressions.

### Phase 2 milestone 2a — Artifact access and request re-derivation (2026-09-17)

Built by Codex via `codex-task.mjs`: `services/proxy` (Go) — `ArtifactCache`
(signature-verified, immutable, push-only from Go callers, no network
surface), `RunJournal` (in-memory stand-in for phase 5's Postgres-backed
journal), `RenderRequest` (independent Go re-implementation of the Python
interpreter's canonical rendering rules — marker substitution, secret
markers preserved unresolved, sorted query/headers, compact sort-keys JSON
body matching Python's `ensure_ascii=True` escaping), and `Authorize`
(protocol steps 1–4 of `SPEC.md` §4.1: fetch+verify artifact, locate step,
verify journaled digest, independently re-render — steps 5–9 are milestones
2b/2c's).

**Caught during independent review**: Codex's `findStep` only matched a
`manifest["plan"]["steps"]` shape — `SPEC.md` §5's *future full node
manifest* shape, which no code in this repo actually produces yet — and its
own test fixtures used that same fabricated shape, so its tests stayed
green while the function silently failed against the plan documents this
codebase actually has today (milestone 1a's schema-validated, 1c's
interpreter-executed bare `{hosts, steps}` document, no `plan` wrapper).
This is the identical defect class caught in milestone 0c's plan-diff fix
two days ago: a fix and its own test agreeing with each other on an
invented shape neither the schema nor the interpreter produces. Reproduced
directly — pushed a real bare-plan-document artifact through `Authorize`
and confirmed a present step was reported "not found." Fixed in
`authorize.go` by falling back to the manifest itself as the plan when no
`plan` key exists. Added `TestAuthorizeAcceptsBarePlanDocumentShape` using
the real shape as a permanent regression test. Re-verified `gate-2a`,
`make check`, `make conform` all green after the fix, no regression on
phases 0–1.

### Milestone 2a second audit pass (2026-09-17) — 4 findings, ALL FIXED

Requested a dedicated audit of already-closed milestone 2a. Claude Code did
an independent read-and-reproduce pass; Codex then ran a second,
independent, read-only pass over the same files with no visibility into
the first pass's findings. Two were caught by both:

**High — FIXED**
- ~~`Authorize()` always called `RenderRequest(step, input, nil)`, hardcoding
  the previous-step/`response` rendering context to nil~~ — fixed: Python's
  `render.py`/`interpreter.py` bind `{{ response.x }}` markers to the
  *previous step's* mapped output, not the live HTTP response of the
  current step. `tests/fixtures/plans/valid/cursor.json` already depends on
  this for pagination (`"cursor": "{{ response.next_cursor }}"`). Reproduced
  directly: re-rendering that fixture's step with a real previous-page
  value produced `cursor=page-2-cursor-abc`; through `Authorize()` it
  rendered `cursor=` (empty). Codex's independent pass reached the same
  finding and sharpened the severity: this doesn't just cause false
  denials, it can let a worker's genuinely divergent request coincide with
  the proxy's wrongly-empty re-derivation, undermining the re-derivation
  guarantee itself. Fixed by Claude Code directly: `JournalEntry` now
  stores a canonical `{"input": ..., "previous": ...}` envelope instead of
  bare input, with the digest covering both; `RunJournal.RecordInput` takes
  a `previous` parameter; `Authorize` decodes both and passes the real
  `previous` context to `RenderRequest`. Added
  `TestAuthorizeUsesJournaledPreviousContext` reproducing the `cursor.json`
  pattern end-to-end through `Authorize`.

**Medium — FIXED**
- ~~`TestNoForbiddenIdentifiers`'s regex
  `(?i)\b(skip_verify|bypass|trusted|danger_full_access)\b` never matched
  Go-idiomatic camelCase/PascalCase identifiers~~ — confirmed independently
  by both audits (word-boundary anchors don't fire inside a camelCase
  transition; `SkipVerify`, `IsTrusted`, `TrustedHost`, `isBypass` all
  evaded it, verified by actually running the regex against sample
  identifiers). This is the exact test CLAUDE.md calls out as enforcing "no
  bypass, ever," and it only caught spellings nothing in idiomatic Go uses.
  Fixed by Codex (dispatched, verified independently after): replaced the
  regex with a `go/scanner`-based tokenizer that inspects only `IDENT`
  tokens, splits on underscores and lower-to-upper camelCase boundaries,
  and matches the banned concepts as whole word-parts regardless of casing
  convention. Verified it now catches `SkipVerify`, `IsTrusted`,
  `TrustedHost`, `isBypass`, `dangerFullAccess`, `skip_verify`, and
  `DANGER_FULL_ACCESS`, while not flagging `Truster` or `trust` inside a
  comment or string literal.
- ~~Header-name collisions after title-casing resolve differently in Python
  and Go~~ — new finding from Codex's pass, independently verified by
  Claude Code by reproducing Python's actual behavior directly: for
  `{"x-a":"lower","X-A":"upper"}` in either key order, Python's `sorted()`
  breaks ties on the *value* (not insertion order) because it compares
  whole `(name, value)` tuples, always keeping `"upper"`; Go was sorting
  raw (pre-title-case) keys and letting the alphabetically-later raw key
  win, always keeping `"lower"` — a schema-valid plan could get different
  authorized header values in worker vs. proxy. Fixed by Codex (dispatched
  together with the U+007F fix below since both touch `render.go`,
  verified independently after): header pairs are now sorted by the full
  `(name, value)` pair matching Python's tuple comparison, with later
  entries in sorted order overwriting earlier ones for the same name,
  reproducing Python's `dict()`-after-`sorted()` semantics exactly.

**Low — FIXED**
- ~~U+007F (DEL) was not escaped by the Go body serializer~~ — Python's
  `json.dumps(..., ensure_ascii=True)` (the default) escapes it as
  ``; confirmed directly (`python3 -c "import json;
  print(json.dumps({'v': chr(0x7f)}))"` → `{"v": ""}`). Go's
  condition was `char < 0x20 || char > 0x7f`, excluding 0x7F itself. Fixed
  by Codex alongside the header-collision fix: condition is now
  `char < 0x20 || char >= 0x7f`.

All four fixes re-verified against a fresh `gate-2a`, `make check`, `make
conform`, and full `go test ./...` — all green, no regressions.

### Audit findings — Phase 0 + Phase 1 (2026-09-17) — ALL 11 FIXED

Two independent audit passes (Codex fresh-context + Claude Code, each
verifying the other's and its own findings by direct reproduction, not
just static reading) found 11 real issues across Phase 0 and Phase 1.
None were new regressions — all were pre-existing gaps in already-gated
code. All 11 were fixed the same day (2026-09-17): the 2 Highs first, then
the 5 Mediums (4 dispatched to Codex in parallel, independently verified —
one required a correction after review caught a gap; see below) and the 4
Lows (fixed directly by Claude Code, per instruction). Every fix was
re-verified against a fresh run of all six milestone gates
(0a/0b/0c/1a/1b/1c) plus `go test`.

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

**Medium — FIXED 2026-09-17**
- ~~`artifact diff`'s plan-change detection ignores step reordering and
  every plan-level field outside `steps` (including a bare-plan `hosts`
  change...)~~ — fixed: `plan_changes` now reports step-order changes,
  duplicate step IDs, and plan-level fields other than `steps`. **Caught
  during independent review**: Codex's first pass and its own test used a
  "hosts nested inside plan" shape that doesn't exist anywhere in this
  codebase, so the actual documented scenario (milestone 1a's bare-plan
  document, `hosts` and `steps` both top-level, no `plan` wrapper) was
  still unfixed. Corrected directly: the "plan sub-object" now falls back
  to the document itself when no `plan` key exists. Added
  `test_bare_plan_document_hosts_change_is_visible` /
  `TestDiffBarePlanDocumentHostsChangeIsVisible` using the real shape so
  this can't regress to the wrong one again.
- ~~Duplicate JSON object keys silently collapse to the last value...~~ —
  fixed: rejected at every nesting level in both languages
  (`object_pairs_hook` in Python; a recursive `json.Decoder.Token()`
  walker in Go, no new dependency). Verified top-level, nested, and
  duplicate-inside-an-array-element cases.
- ~~Dev-keygen overwrite protection is TOCTOU-vulnerable...~~ — fixed:
  atomic `O_CREAT|O_EXCL` (Python `os.open`) / `O_CREATE|O_EXCL` (Go
  `os.OpenFile`) create in both languages, permissions set at creation
  (no separate `chmod`), with cleanup of a just-created private key if the
  matching public key's creation then fails.
- ~~The interpreter has no bound on a single response's byte size...~~ —
  fixed: bounded read (1 MiB cap, matching `SPEC.md`'s own example) via
  chunked reads before JSON parsing, raising `ResponseTooLargeError`
  rather than buffering unbounded bytes first.
- ~~Request rendering in the interpreter doesn't sort query parameters or
  normalize header casing...~~ — fixed: query params sorted by key,
  headers normalized to consistent title-case, both before rendering.

**Low — FIXED 2026-09-17 (by Claude Code directly, per instruction)**
- ~~Python and Go disagree on acceptance of an unpaired UTF-16 surrogate
  escape...~~ — fixed: `canonical.go` now pre-scans raw JSON text for
  `\uXXXX` escapes inside string literals and rejects a lone surrogate
  half, matching Python. Has to happen on the raw bytes, since by the time
  `json.Decoder` returns a string an invalid escape is already silently
  replaced — indistinguishable at that point from a legitimate literal
  U+FFFD character. Verified against every edge case: lone high/low
  surrogates rejected, valid pairs still combine correctly, an escaped
  backslash before literal `u0041` isn't misdetected, a genuine U+FFFD
  character is unaffected, and a pair inside an object *key* is caught too.
- ~~Deeply nested input raises an uncaught `RecursionError`...~~ — fixed:
  `canonicalize()` catches `RecursionError` around both parsing and
  re-encoding, re-raising as `CanonicalizationError`.
- ~~`chmod(0o600)` happens after the write...~~ — resolved as a byproduct
  of the keygen TOCTOU fix above (permissions are now set atomically at
  creation, so there's no longer a separate `chmod` step at all).
- ~~CRLF injected into a rendered header value... doesn't translate into a
  controlled `PlanRejected`...~~ — fixed as part of the interpreter
  Medium fixes above: the underlying `ValueError` is now caught and
  re-raised as `PlanRejected`.

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
