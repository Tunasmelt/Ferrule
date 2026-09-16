---
name: orchestrator
description: >
  Runs a feature from idea to PR through gated phases — spec, design, plan, API
  verification, TDD, independent review, and PR checks — where each gate is a
  real script exit code, not a judgement call. Use this skill when the user
  starts new feature work, says "build X", "add feature Y", "let's implement Z",
  asks to run the pipeline, mentions gates or phases, or wants to resume an
  in-progress feature. Also use when the user asks what phase they're on or why
  a gate is failing.
---

# Orchestrator — gated feature pipeline

One command drives the whole feature. Each phase ends in a gate that must pass
before the next begins. Gates are enforced by `gate.mjs` exit codes — never by
your judgement about whether things look finished.

## The pipeline

```
spec → design → plan → api → tdd → review → pr
```

| Gate | Passes when |
|------|-------------|
| spec | spec.md exists, has `- [ ]` acceptance criteria, human approved |
| design | design.md exists (auto-skips for non-UI features) |
| plan | plan.md has tasks, every task names a file |
| api | every API in config.apis has fresh docs |
| tdd | test files exist AND `commands.test` exits 0 |
| review | fresh-context reviewer found no BLOCKING findings |
| pr | lint + typecheck + security pass, changelog entry for today |

## Commands

```bash
node agent-os/gate.mjs --start "<feature>"    # begin (add --no-design for non-UI)
node agent-os/gate.mjs --status               # where am I
node agent-os/gate.mjs --next                 # check the current gate
node agent-os/gate.mjs --advance              # record a pass, move on
node agent-os/gate.mjs <gate>                 # check any gate directly
node agent-os/gate.mjs --list                 # all gates
```

Artifacts live in `.agent/run/<slug>/`. State is on disk, so a run survives a
context clear — `--status` always tells you where you are.

## How to drive it

**Starting.** Ask what the feature is. Run `--start "<description>"`. If it has
no UI, pass `--no-design`.

**Each phase.** Write the artifact the gate wants, then run `--next` to check.
If it fails, the output says exactly what's missing — fix that, re-check. Only
run `--advance` once the gate passes.

**Never skip a gate by editing state.** If a gate is wrong, fix the gate, not
`.agent/run/current.json`.

## Writing each artifact

**spec.md** — the problem, what's in scope, what's explicitly out, and
acceptance criteria as a `- [ ]` checklist. Criteria must be observable: "user
sees an error toast when payment fails", not "handles errors well". The gate
counts them; you and the user judge whether they're real.

Advancing past spec is a human act. Show the spec, ask for approval, and only
then run `--advance`.

**design.md** — only for UI work. Layout, states (empty/loading/error), and the
interaction. Skip for pure backend features.

**plan.md** — tasks as `- [ ]`, each naming the file it touches in backticks.
The gate rejects any task without a file — a task without a file is a wish. Aim
for tasks small enough to do in a few minutes each.

**tests before implementation.** The tdd gate checks that test files exist and
pass. Write failing tests from the acceptance criteria first, then implement
until they pass. Don't write the implementation and backfill tests — that's not
what the gate is for, even though it can't tell the difference.

**changelog** — an entry dated today in CHANGELOG.md before the pr gate.

## Gate statuses

- `PASS` — verified, move on.
- `FAIL` — blocked, exit 1. Fix and re-check.
- `SKIP` — legitimately not applicable (no UI, no APIs declared).
- `UNAVAILABLE` — **the checker doesn't exist yet.** Does not block, but it is
  NOT a pass. Tell the user plainly that this was not verified and they should
  check it themselves. Never report an UNAVAILABLE gate as if it passed.

## When a gate fails

Read the reason and the detail — they name the specific problem. Fix the
underlying thing, never the gate. If a gate seems wrong (a rule that doesn't fit
this project), say so and suggest changing `.agent/config.json` or the gate
itself, rather than working around it.

## At session end

Write `HANDOFF.md` with `### Decisions` and `### Gotchas` bullets, then run
`node agent-os/memory-sync.mjs` so the decisions reach tiered memory.

## Supporting scripts

```bash
node agent-os/api-check.mjs --detect      # propose APIs to declare in config
node agent-os/api-check.mjs --scaffold    # create doc stubs
node agent-os/api-check.mjs               # freshness status (api gate uses this)
node agent-os/security-check.mjs          # full report + manual checklist
node agent-os/jargon-extract.mjs          # propose domain vocabulary
node agent-os/memory-sync.mjs             # session end: handoff -> tiered memory
node agent-os/memory-consolidate.mjs      # memory health report
```

## Orchestrating Codex for a milestone's coding work

You (Claude Code) are the orchestrator. For a bounded coding subtask inside
the current milestone:

```bash
node agent-os/scripts/claim.mjs status                                  # make sure nobody else has it
node agent-os/scripts/codex-task.mjs --milestone <id> --prompt "<task>" # dispatch, blocks until Codex returns
```

Then, always: read the printed log path and last message, look at the actual
diff yourself, and run the milestone's gate from `docs/PHASES.md`
(`make gate-<id>`). `codex-task.mjs` claims and releases the milestone for
you but does none of that review — it is a dispatch call, not a merge.
Never dispatch an open-ended prompt; split multi-part work into one dispatch
per bounded piece. See `CLAUDE.md`'s "Orchestration" section for the full
protocol, including how Cline/Antigravity fit in (manually, no dispatcher).

**Before writing any code that calls an external API**, the api gate must pass.
Fetch the real docs for the version actually installed, record endpoints,
signatures, and especially model IDs in `.agent/api-docs/<name>.md`, then set
`verified:` to today. Never write integration code from recalled knowledge —
that is the single most common source of confidently wrong AI code.
