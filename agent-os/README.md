# agent-os

A stack-agnostic agent operating system. Plain `.mjs` files — no build step, no
bash, no installer. Works on Windows, macOS, and Linux wherever Node runs.

## Install

Drop the `agent-os/` folder at your project root:

```
your-project/
  agent-os/
    SKILL.md
    scripts/
      lib/config.mjs        ← every script imports this
      bootstrap.mjs
      gate.mjs
      api-check.mjs
      security-check.mjs
      jargon-extract.mjs
      memory-sync.mjs
      memory-consolidate.mjs
```

Keep `lib/` inside `scripts/` — the relative import is `./lib/config.mjs`.

Then scaffold the workspace once:

```bash
node agent-os/scripts/bootstrap.mjs --yes
```

That creates `.agent/` with `config.json`, tiered memory, `JARGON.md`,
`FEATURES.md`, and a `rules/` folder.

## What makes it stack-agnostic

Nothing hardcodes a command or a path. Every script reads `.agent/config.json`,
which your project declares for itself:

```json
{
  "language": "typescript",
  "commands": { "test": "pnpm test", "lint": "pnpm lint", "audit": "pnpm audit" },
  "rules": [".agent/rules/style.md"],
  "sourceDirs": ["app", "lib"],
  "apis": [{ "name": "Stripe", "pkg": "stripe", "docs": "https://docs.stripe.com/api" }]
}
```

A Python project writes `"test": "pytest"` and the identical scripts work.
Bootstrap detects Node, Python, Go, and Rust and proposes commands; an unknown
stack degrades with an explicit warning rather than a fabricated default.

## The pipeline

```bash
node agent-os/scripts/gate.mjs --start "add gem purchase" [--no-design]
node agent-os/scripts/gate.mjs --status     # where am I
node agent-os/scripts/gate.mjs --next       # check the current gate
node agent-os/scripts/gate.mjs --advance    # record a pass, move on
```

| Gate | Enforced by | Status |
|------|-------------|--------|
| spec | spec.md has `- [ ]` criteria + human approval | ✅ real |
| design | design.md exists (auto-skips non-UI) | ✅ real |
| plan | every task names a file | ✅ real |
| api | api-check.mjs — declared APIs have fresh docs | ✅ real |
| tdd | test files exist AND `commands.test` exits 0 | ✅ real |
| review | fresh-context reviewer | ⚠️ **not built yet** |
| pr | lint + typecheck + security-check + changelog | ✅ real |

**The review gate reports UNAVAILABLE, not PASS.** A gate whose checker doesn't
exist announces that loudly rather than showing a fake green light. Review your
own diffs until it's built.

## Standalone scripts

```bash
node agent-os/scripts/api-check.mjs --detect     # propose APIs for config
node agent-os/scripts/api-check.mjs --scaffold   # create doc stubs
node agent-os/scripts/api-check.mjs              # freshness status
node agent-os/scripts/security-check.mjs         # automated + manual checklist
node agent-os/scripts/jargon-extract.mjs         # propose domain vocabulary
node agent-os/scripts/memory-sync.mjs            # HANDOFF.md -> tiered memory
node agent-os/scripts/memory-consolidate.mjs     # memory health report
```

## Orchestration (Claude Code + Codex)

Two more scripts turn agent-os into a light multi-agent protocol: Claude Code
plans and reviews, Codex executes bounded coding subtasks non-interactively.

```bash
node agent-os/scripts/claim.mjs claim <milestone> <owner>   # claim before touching a milestone
node agent-os/scripts/claim.mjs release <milestone> [done|failed]
node agent-os/scripts/claim.mjs status [milestone]           # who owns what, right now

node agent-os/scripts/codex-task.mjs --milestone <id> --prompt "<task>"
node agent-os/scripts/codex-task.mjs --milestone <id> --prompt-file <path> --sandbox read-only
```

`claim.mjs` is a file-based mutex over `.agent/orchestration/claims.json` —
claiming a milestone another owner has `in_progress` fails loudly instead of
silently overwriting. `codex-task.mjs` claims a milestone, runs `codex exec`
in a sandbox (auto-detects the CLI on PATH or bundled in a VS Code OpenAI
extension install), logs the full JSONL event stream under
`.agent/orchestration/logs/`, and releases the claim on exit — it never
reviews the diff or runs the milestone's gate itself. That stays a human/
Claude-Code step, every time.

Cline and Antigravity have no headless CLI, so there's no dispatcher for
them — hand them a milestone's written brief manually and claim the milestone
first regardless.

Every script supports `--help` and `--json`.

## Tiered memory (a token budget, not note-taking)

```
.agent/memory/
  index.md        Layer 1 — read every turn. Pointers only, ~150 char cap.
  decisions/      Layer 2 — one file opened on demand, never bulk-read.
  patterns/
  knowledge/
  blockers/
  transcripts/    Layer 3 — never auto-read. Grep only.
```

At session end, write `HANDOFF.md` with `### Decisions` and `### Gotchas` bullet
lists, then run `memory-sync.mjs`. Decisions become topic files, gotchas become
blockers, the whole session is archived for grepping, and one short pointer line
per entry is appended to `index.md`.

Run `memory-consolidate.mjs` weekly. It reports duplicate pointers, oversized
summaries, broken pointers, orphaned files, and stale topics — and never deletes
anything.

## Honest limitations

- **The review gate isn't built.** Six of seven gates are real.
- **When built, the reviewer gets fresh context, not a different model.** Context
  isolation kills reviewer anchoring, which is the high-value 80%. True
  cross-model review needs an API key and is a separate opt-in.
- **security-check is pattern matching, not static analysis.** It has language
  packs for JS/TS, Python, Go, Ruby, PHP, Java, and Rust. An unknown stack runs
  universal checks only and says so explicitly — it will never imply coverage it
  doesn't have. Nine business-logic items (RLS, record access, field tampering)
  are printed as a manual checklist and are never auto-passed.
- **jargon-extract proposes, it can't judge.** It ranks words that name folders
  and files highest, since people name paths after domain concepts. Expect to
  delete half of what it suggests.
- **The tdd gate can't tell test-first from test-after.** It verifies tests exist
  and pass. Writing them first is on you.

## Not included

`gap-check` and `ralph-loop` (the autonomous build loop) are specced but not
built. `ctx-map`/`ctx-search` were deliberately dropped — graphify does that
job better.
