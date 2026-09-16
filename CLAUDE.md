# CLAUDE.md — Ferrule

Instructions for agents working in this repository. Read this before writing
code. Read `docs/SPEC.md` before changing anything about plans, the proxy, or
node artifacts.

This repo is also worked on via Codex, which reads `AGENTS.md`. The two files
must agree on invariants, layout and phase discipline — only tool-specific
workflow mechanics differ. If you change a rule here, check whether
`AGENTS.md` needs the same change.

---

## What this project is

Ferrule compiles API documentation into **verified integration nodes** — signed,
immutable artifacts carrying their own schemas, permissions, tests and
provenance, monitored for upstream change after deployment.

The product is **not** the code generator. It is everything between *generated*
and *trusted in production*.

---

## Non-negotiable invariants

Violating any of these is a bug regardless of tests passing. If a change
requires breaking one, stop and raise it rather than working around it.

1. **Secrets never enter the worker process.** Plans contain `{{ secret.NAME }}`
   markers. Only `egress-proxy` resolves them. No code path may read credential
   material into a worker.

2. **Every outbound request is plan-bound.** The proxy re-derives the expected
   request from the signed artifact and compares. Never add a "trusted" bypass,
   not even for testing. Tests use a test artifact, not a bypass flag.

3. **Workflows reference `artifact_hash`, never a slug or a mutable pointer.**
   If you find code resolving a node by name at run time, that is a bug.

4. **Approved artifacts are immutable.** Regeneration creates a new version.
   There is no update path on an approved `node_version` row other than
   `status`.

5. **Template rendering is canonical and deterministic.** Sorted query params,
   normalized header casing, stable JSON key order. No time, randomness, or
   environment access in templates. Non-determinism here causes false denials.

6. **Redaction happens before persistence, never after.** No raw credential or
   sensitive field may be written to Postgres, object storage, or logs and then
   cleaned up.

7. **The expression language is CEL.** Never `eval`, never Jinja with attribute
   access, never a regex templater. No custom CEL extension functions in v1.

8. **Fixture replay against a live API is read-only nodes only.** Enforced in
   code, not by convention.

9. **`plan_coverage` is recorded on every compile attempt**, including failures.
   This number decides the product roadmap.

---

## Repository layout

```
/services
  /api            FastAPI — public HTTP surface
  /compiler       Python — ingest, extract, generate, verify
  /registry       Python — artifact store, signing, diffing
  /workflow       Python — graph definitions, port validation
  /policy         Python — RBAC, approval gates
  /orchestrator   Python — durable run state machine
  /worker         Python — plan interpreter
  /proxy          Go — plan-bound authorization + credential injection
  /drift          Python — fingerprinting, baselines
/packages
  /plan-schema    JSON Schema + CEL type defs for the plan language
  /artifact       artifact build, hash, sign, verify (shared Python + Go)
/docs             SPEC, ARCHITECTURE, API, PHASES, HANDOFF
/cli              ferrule CLI (v1 primary interface)
render.yaml       infrastructure blueprint
```

**`packages/artifact` has two implementations** (Python for the compiler, Go for
the proxy). They must produce identical canonical bytes. There is a
cross-language conformance test suite — run it on any change to canonicalization.

---

## Working practices

**Per-feature pipeline.** `agent-os/` (see `agent-os/SKILL.md`) drives a single
feature through gated phases — spec → plan → api → tdd → pr (design is
skipped: no UI in v1) — with each gate a real `.agent/config.json`-configured
script exit code, state persisted in `.agent/run/<slug>/`. Use it for
individual features inside a `docs/PHASES.md` milestone; it does not replace
the milestone gates and it does not coordinate multiple agents — it is a
disk-persisted checklist any single agent picks up and continues. Its `review`
gate is not built (`UNAVAILABLE`, not a pass) — review your own diffs, or run
the `requesting-code-review` skill, until it is.

**Orchestration: Claude Code directs, Codex codes.** Claude Code is the
orchestrator and the watcher — it plans milestones, dispatches bounded coding
subtasks to Codex, reviews what comes back, and runs the gate. It does not
hand off control; Codex runs non-interactively and returns.

- `node agent-os/scripts/claim.mjs claim <milestone> <owner>` before either
  side starts touching a milestone's files. Claiming a milestone another owner
  has `in_progress` fails loudly — that failure is the point, not a bug to
  route around. `status` (no args) lists everything; `release <milestone>
  [done|failed]` frees it.
- `node agent-os/scripts/codex-task.mjs --milestone <id> --prompt "<task>"`
  dispatches ONE bounded coding subtask to Codex (claims the milestone,
  runs `codex exec` sandboxed, logs the full JSONL event stream to
  `.agent/orchestration/logs/`, releases the claim). "Bounded" means one
  milestone, one prompt, one sandbox — split anything bigger and dispatch each
  piece separately rather than writing an open-ended prompt.
- The script never reviews Codex's diff or runs the milestone's gate — that is
  the orchestrator's job, every time, after every dispatch. Read the returned
  log and last message, look at the actual file changes, then run that
  milestone's `make gate-<id>` yourself before considering it done.
- Use `--sandbox read-only` to have Codex investigate or plan without writing
  anything; `workspace-write` (the default) lets it edit files in this repo.
  Never pass `danger-full-access` from an automated call.
- Cline and Antigravity have no headless invocation surface — there is no
  script for them. Hand them a milestone's written brief (its `spec.md`/
  `plan.md` under `.agent/run/<slug>/`, or a `docs/PHASES.md` milestone
  section) manually, and still claim the milestone first so Codex doesn't pick
  up the same one.

### Before implementing

Use the `brainstorming` skill for any new feature or behaviour change, and
`writing-plans` before multi-step work. Do not start coding from a one-line
description.

### While implementing

- **TDD.** Use `test-driven-development`. This codebase is security-relevant;
  tests before implementation is not optional here.
- **API calls to external services.** Use `api-check` before writing or
  modifying any code that calls a third-party API or SDK. Model strings and
  endpoint signatures in training data are frequently stale.
- **Debugging.** Use `systematic-debugging`. Do not propose fixes before
  reproducing.

### Before claiming done

Use `verification-before-completion`. Run the command, read the output, then
make the claim. "Should work" is not a completion state.

Run before any completion claim:

```bash
make check     # lint, typecheck, unit tests
make conform   # cross-language artifact canonicalization conformance
make security  # permission probe suite against the proxy
```

### Before merging

Use `requesting-code-review`, then `finishing-a-development-branch`. Any change
touching `/services/proxy`, `/packages/artifact`, or the plan schema requires an
explicit review pass against the invariants above.

---

## Conventions

**Python:** FastAPI, Pydantic v2 for all boundary types, `ruff` + `mypy --strict`
on `/services` and `/packages`. No bare `except`. No `Any` in a public signature.

**Go (proxy only):** standard library first. Every new dependency needs
justification in the PR — this binary's dependency surface is a security
property.

**Errors:** every failure path maps to a `failure_class` from `SPEC.md` §7.
Never invent a new class without updating the spec.

**Migrations:** forward-only. The run journal is append-only; never add an
`UPDATE` path to `run_events`.

**Logging:** structured, `run_id` and `node_version_hash` on every line in the
data plane. Redact at the emit site.

---

## Things agents get wrong here

Observed failure patterns worth stating explicitly:

- **Adding a bypass for local development.** The proxy's whole value is that
  there is no bypass. Run a local proxy instance instead.
- **Resolving nodes by slug because it is convenient in a test.** Breaks
  invariant 3 and the test will pass while the product claim becomes false.
- **Using Jinja because the templating "just needs to be simple".** Breaks
  invariant 7. The plan language is CEL plus a fixed template renderer.
- **Rendering templates in the worker and sending the result to the proxy for
  approval.** The proxy must re-render independently. Sending the rendered
  request *as well* is correct; sending it *instead* defeats the mechanism.
- **Treating the capability manifest as the authorization source.** It is
  defence-in-depth. The plan is the authorization source.
- **Widening drift severity.** Severity is scoped to mapped fields
  (`SPEC.md` §6.3). Alerting on unmapped field changes makes the feature noise.

---

## Current phase

See `docs/PHASES.md`. Each phase is now broken into sequential milestones
(e.g. phase 2 has milestones 2a–2d), each with its own test criteria,
security criteria and gate command (`make gate-2a`, etc.). Do not build ahead
of the current milestone's gate — later milestones in a phase usually depend
on interfaces or data models the earlier one froze. The phase-level gate
(`make gate-2`) is the union of that phase's milestone gates.

Ship order is deliberate: **enforcement before generation.** Phase 2 (proxy)
precedes phase 3 (compiler). Retrofitting a security model onto a working
generator is the failure mode that kills products in this category. The same
principle applies inside a phase — see `docs/PHASES.md` for milestone
ordering rationale.

When working alongside another agent (e.g. Codex on `AGENTS.md`), treat a
milestone as the unit of handoff: claim one before starting it, and don't
open the next milestone in the same phase until the current one's gate is
green.
