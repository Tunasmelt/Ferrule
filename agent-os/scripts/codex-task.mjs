#!/usr/bin/env node
// codex-task.mjs — dispatch one bounded coding subtask to Codex non-interactively.
//
// This is the real link in the Claude-orchestrates / Codex-codes setup: Claude
// Code (or you) calls this, it claims the milestone so nothing else can touch
// it concurrently, runs `codex exec` in this repo with a sandbox, streams the
// JSONL event log to disk, and releases the claim when Codex finishes.
//
// Claude Code never edits Codex's files directly while a claim is in_progress —
// check `node claim.mjs status` first if that's unclear.
//
// Usage:
//   node codex-task.mjs --milestone 0a --prompt "Implement ..." [--owner codex]
//   node codex-task.mjs --milestone 0a --prompt-file .agent/run/0a/plan.md
//   node codex-task.mjs --milestone 0a --prompt "..." --sandbox read-only   (dry run / read-only investigation)
//
// What it does NOT do: review the diff, run the milestone's gate, or merge
// anything. That's the orchestrator's job, after this returns — see
// docs/PHASES.md and CLAUDE.md's "Per-feature pipeline" section.

import { existsSync, readFileSync, mkdirSync, appendFileSync, writeFileSync } from "node:fs";
import { spawnSync } from "node:child_process";
import { join, dirname } from "node:path";
import { homedir, platform } from "node:os";
import { globSync } from "node:fs";
import { c, hasFlag, getArg, handleHelp, fail } from "./lib/config.mjs";
import { claim, release, newLogPath } from "./lib/claims.mjs";

handleHelp(`
codex-task.mjs — dispatch a bounded coding subtask to Codex (non-interactive)

Usage:
  node codex-task.mjs --milestone <id> --prompt "<instructions>" [options]
  node codex-task.mjs --milestone <id> --prompt-file <path> [options]

Options:
  --owner <name>        claim owner recorded in the ledger (default: codex)
  --sandbox <mode>      read-only | workspace-write (default) | danger-full-access
  --model <name>        override Codex's model
  --cwd <dir>           working root Codex should use (default: repo root)
  --codex-bin <path>    explicit path to codex/codex.exe, skips auto-detection
  --json                print the machine-readable summary instead of prose

Bounded means: one milestone, one prompt, one sandbox. Do not use this to run
an open-ended, multi-milestone task — split it and dispatch each piece.
`);

const JSON_MODE = hasFlag("--json");
const milestone = getArg("--milestone");
const owner = getArg("--owner", "codex");
const promptFile = getArg("--prompt-file");
const promptArg = getArg("--prompt");
const sandbox = getArg("--sandbox", "workspace-write");
const model = getArg("--model");
const cwd = getArg("--cwd", process.cwd());
const explicitBin = getArg("--codex-bin");

if (!milestone) fail("Missing --milestone <id>. See docs/PHASES.md for valid milestone ids.");
if (!promptArg && !promptFile) fail("Provide --prompt \"<text>\" or --prompt-file <path>.");

const prompt = promptFile
  ? (() => {
      if (!existsSync(promptFile)) fail(`--prompt-file not found: ${promptFile}`);
      return readFileSync(promptFile, "utf8");
    })()
  : promptArg;

// ── Locate the codex binary ────────────────────────────────────────────────
// Prefer a real PATH install; fall back to the copy bundled with the OpenAI
// ChatGPT / Codex VS Code extension, since that's how it's installed here.

function findOnPath() {
  const cmd = platform() === "win32" ? "where" : "which";
  const r = spawnSync(cmd, ["codex"], { encoding: "utf8" });
  if (r.status === 0) {
    const first = r.stdout.split(/\r?\n/).map((s) => s.trim()).find(Boolean);
    if (first) return first;
  }
  return null;
}

function findBundledInExtensions() {
  const extRoots = [
    join(homedir(), ".vscode", "extensions"),
    join(homedir(), ".vscode-insiders", "extensions"),
  ];
  const suffix =
    platform() === "win32"
      ? "bin/windows-x86_64/codex.exe"
      : platform() === "darwin"
        ? "bin/aarch64-apple-darwin/codex"
        : "bin/linux-x86_64/codex";
  for (const root of extRoots) {
    if (!existsSync(root)) continue;
    try {
      const matches = globSync(join(root, "openai.chatgpt-*", suffix));
      if (matches.length) return matches.sort().at(-1); // newest version string wins
    } catch {
      // globSync (Node 22+) may be unavailable — best-effort only.
    }
  }
  return null;
}

function findCodexBinary() {
  if (explicitBin) {
    if (!existsSync(explicitBin)) fail(`--codex-bin not found: ${explicitBin}`);
    return explicitBin;
  }
  return findOnPath() || findBundledInExtensions();
}

const codexBin = findCodexBinary();
if (!codexBin) {
  fail(
    "Could not find a codex binary. Install the CLI, or pass --codex-bin explicitly " +
      "(the OpenAI ChatGPT VS Code extension bundles one under its bin/ folder)."
  );
}

// ── Claim the milestone ─────────────────────────────────────────────────────

let claimRecord;
try {
  claimRecord = claim(milestone, owner, prompt.slice(0, 200));
} catch (err) {
  fail(err.message);
}

console.log(c.dim(`Using codex binary: ${codexBin}`));
console.log(c.green(`✓ Claimed ${milestone} for ${owner}`));

// ── Run codex exec ───────────────────────────────────────────────────────────

const logPath = newLogPath(milestone, owner);
mkdirSync(dirname(logPath), { recursive: true });
const lastMessagePath = logPath.replace(/\.jsonl$/, ".last-message.txt");

const args = [
  "exec",
  "-C", cwd,
  "--sandbox", sandbox,
  "--skip-git-repo-check",
  "--json",
  "-o", lastMessagePath,
  prompt,
];
if (model) args.splice(args.indexOf("exec") + 1, 0, "-m", model);

console.log(c.bold(`\nDispatching to Codex — milestone ${milestone}, sandbox ${sandbox}\n`));

const child = spawnSync(codexBin, args, {
  cwd,
  encoding: "utf8",
  maxBuffer: 1024 * 1024 * 64,
});

// Persist the full JSONL event stream regardless of outcome — this is the
// audit trail an orchestrator reads back, not just the final message.
writeFileSync(logPath, child.stdout || "");
if (child.stderr) appendFileSync(logPath, "\n\n# stderr\n" + child.stderr);

const succeeded = child.status === 0;
const lastMessage = existsSync(lastMessagePath) ? readFileSync(lastMessagePath, "utf8") : null;

release(milestone, succeeded ? "done" : "failed", succeeded ? "codex exec succeeded" : `exit ${child.status}`);

const summary = {
  milestone,
  owner,
  succeeded,
  exitCode: child.status,
  logPath,
  lastMessagePath: existsSync(lastMessagePath) ? lastMessagePath : null,
};

if (JSON_MODE) {
  console.log(JSON.stringify(summary, null, 2));
} else {
  console.log(succeeded ? c.green(`✓ Codex finished (exit 0)`) : c.red(`✗ Codex exited ${child.status}`));
  console.log(`  Event log:     ${logPath}`);
  if (lastMessage) {
    console.log(c.bold("\n  Last message:"));
    console.log(
      lastMessage
        .trim()
        .split(/\r?\n/)
        .map((l) => "    " + l)
        .join("\n")
    );
  }
  console.log(
    c.dim(
      `\nClaim released. Next: review the diff yourself and run this milestone's gate ` +
        `(see docs/PHASES.md) — this script does not do either.`
    )
  );
}

process.exit(succeeded ? 0 : 1);
