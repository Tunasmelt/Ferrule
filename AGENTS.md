# AGENTS.md — Ferrule

Instructions for agents (Codex and others) working in this repository.
Read this before writing code. Read `docs/SPEC.md` before changing anything
about plans, the proxy, or node artifacts.

This file is the Codex-facing counterpart to `CLAUDE.md`. The two must stay
in sync on substance — invariants, layout, conventions, phase discipline are
identical. Only the tool-specific workflow guidance differs. If you edit one,
check whether the other needs the same edit.

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
disk-persisted checklist any single agent (Claude Code or Codex) picks up and
continues. Its `review` gate is not built (`UNAVAILABLE`, not a pass) — get an
explicit review pass yourself until it is.

**Orchestration: Codex runs as a dispatched worker, Claude Code directs.**
When you (Codex) are invoked through `agent-os/scripts/codex-task.mjs` rather
than interactively, you have been dispatched for ONE bounded milestone task —
do that task, do not expand scope to neighboring milestones, and do not start
a second milestone on your own initiative. The dispatcher already claimed the
milestone in `.agent/orchestration/claims.json` before invoking you; if you
are ever run some other way, run
`node agent-os/scripts/claim.mjs claim <milestone> codex` yourself first, and
`release` it when done (`done` or `failed`) — never leave a milestone claimed
`in_progress` when you stop working on it. Claude Code reviews your diff and
runs the milestone's gate afterward; you do not need to (and should not
assume you can) merge or advance `agent-os` state yourself.

### Before implementing

Do not start coding from a one-line description. For any new feature or
behaviour change, write down — in the PR description or a short scratch note,
not necessarily a committed doc — what you're building, why, and which
milestone in `docs/PHASES.md` it belongs to. For anything touching more than
one service, sketch the approach and the files you expect to touch before
opening files to edit.

### While implementing

- **TDD.** This codebase is security-relevant; write the failing test before
  the implementation. This is not optional here, especially for
  `/services/proxy`, `/packages/artifact`, and the plan interpreter.
- **API calls to external services.** Before writing or modifying any code
  that calls a third-party API or SDK, verify current method signatures,
  auth flows and rate-limit behaviour against that provider's live docs —
  do not rely on training-data recall, which is frequently stale.
- **Debugging.** Reproduce before proposing a fix. Do not patch symptoms in
  the proxy or interpreter without a failing test that demonstrates the bug.

### Before claiming done

Run the command, read the output, then make the claim. "Should work" is not
a completion state.

Run before any completion claim:

```bash
make check     # lint, typecheck, unit tests
make conform   # cross-language artifact canonicalization conformance
make security  # permission probe suite against the proxy
```

For a milestone-scoped change, also run that milestone's own gate command
from `docs/PHASES.md` (e.g. `make gate-2b`) — the phase-level gate is a
sum of milestone gates and is not itself run until every milestone in that
phase is closed.

### Before merging

Get an explicit review pass against the invariants above for any change
touching `/services/proxy`, `/packages/artifact`, or the plan schema. Do not
self-merge those without one, regardless of which agent or tool did the
review.

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
- **Jumping ahead to the phase-level gate.** `docs/PHASES.md` now defines
  milestones inside each phase, each with its own gate. Close milestones in
  order; do not start milestone N+1's deliverables before milestone N's gate
  is green.

---

## Working side by side with another agent/tool

This repository is worked on by multiple agent tools (Claude Code via
`CLAUDE.md`, Codex via this file, possibly others). To avoid collisions:

- Treat `docs/PHASES.md` milestones as the unit of work handoff. Before
  starting a milestone, check its checklist isn't already mid-flight in
  another branch or worktree.
- Do not edit `CLAUDE.md` and `AGENTS.md` to diverge on invariants, layout,
  or phase discipline — they describe the same rules to different tools.
  Tool-specific workflow mechanics (which command runs tests, which review
  step to invoke) may differ; the engineering rules may not.
- Commit messages and PR descriptions should state which milestone (not just
  which phase) the change closes, e.g. `phase-2 / milestone-2b: redirect and
  budget enforcement`.

---

## Current phase

See `docs/PHASES.md`. Do not build ahead of the current milestone's gate.
Each gate is a real command with a real exit code, not a judgement call.

Ship order is deliberate: **enforcement before generation.** Phase 2 (proxy)
precedes phase 3 (compiler). Retrofitting a security model onto a working
generator is the failure mode that kills products in this category.
