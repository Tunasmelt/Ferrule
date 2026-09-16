#!/usr/bin/env node
// gate.mjs — Run a named quality gate. Exits 0 on pass, 1 on fail.
//
// A gate is REAL: it either runs a command and reads its exit code, or checks a
// file condition. It never asks an agent whether things look good. Gates whose
// checker script isn't built yet report UNAVAILABLE loudly rather than passing
// silently — a fake green light is worse than no gate at all.
//
// Usage:
//   node gate.mjs --start "add gem purchase"   begin a run
//   node gate.mjs spec                          check one gate
//   node gate.mjs --next                        check the current gate
//   node gate.mjs --advance                     record a pass, move on
//   node gate.mjs --status                      where am I
//   node gate.mjs --list                        all gates and what they check

import { existsSync, readFileSync, writeFileSync, mkdirSync, readdirSync } from "node:fs";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";
import { execSync } from "node:child_process";
import {
  loadConfig, getCommand, c, hasFlag, getArg, handleHelp, AGENT_DIR, fail,
} from "./lib/config.mjs";

handleHelp(`
gate.mjs — quality gates for the build pipeline

Usage:
  node gate.mjs --start "<feature description>"   start a run
  node gate.mjs --status                          show current position
  node gate.mjs --next                            check the current gate
  node gate.mjs <gate>                            check a specific gate
  node gate.mjs --advance                         record pass, move to next gate
  node gate.mjs --list                            list all gates
  node gate.mjs --json                            machine-readable

Gates: spec  design  plan  api  tdd  review  pr
Exit code 0 = passed or skipped, 1 = failed.
`);

const config = loadConfig();
const JSON_MODE = hasFlag("--json");
const RUN_DIR = join(AGENT_DIR, "run");
const STATE_PATH = join(RUN_DIR, "current.json");
const SCRIPT_DIR = join(AGENT_DIR, "scripts");

const GATE_ORDER = ["spec", "design", "plan", "api", "tdd", "review", "pr"];

// ── Run state ───────────────────────────────────────────────────────────────

function loadState() {
  if (!existsSync(STATE_PATH)) return null;
  try {
    return JSON.parse(readFileSync(STATE_PATH, "utf8"));
  } catch {
    fail(`${STATE_PATH} is corrupt. Delete it to start over.`);
  }
}

function saveState(state) {
  mkdirSync(RUN_DIR, { recursive: true });
  writeFileSync(STATE_PATH, JSON.stringify(state, null, 2) + "\n");
}

function slugify(s) {
  return s.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "").slice(0, 50);
}

// ── Result helpers ──────────────────────────────────────────────────────────
// PASS / FAIL / SKIP / UNAVAILABLE. UNAVAILABLE means the checker doesn't exist
// yet — it does not block, but it must be impossible to miss.

const PASS = (reason, detail) => ({ status: "PASS", reason, detail });
const FAIL_ = (reason, detail) => ({ status: "FAIL", reason, detail });
const SKIP = (reason) => ({ status: "SKIP", reason });
const UNAVAILABLE = (reason, detail) => ({ status: "UNAVAILABLE", reason, detail });

function runCommand(cmd) {
  try {
    const out = execSync(cmd, { stdio: ["ignore", "pipe", "pipe"], encoding: "utf8" });
    return { ok: true, out };
  } catch (err) {
    return { ok: false, out: (err.stdout || "") + (err.stderr || "") };
  }
}

/** Path to a run artifact, e.g. spec.md for the active feature. */
function artifact(state, name) {
  return join(RUN_DIR, state.slug, name);
}

// Sibling scripts live next to this one, wherever that is. Resolving relative
// to import.meta.url means the layout can be agent-os/scripts/, .agent/scripts/,
// or anything else without gate.mjs needing to guess.
const HERE = dirname(fileURLToPath(import.meta.url));

const SCRIPT_SEARCH = [
  HERE,
  join(AGENT_DIR, "scripts"),
  join("agent-os", "scripts"),
  "agent-os",
];

function scriptPath(name) {
  for (const dir of SCRIPT_SEARCH) {
    const p = join(dir, name);
    if (existsSync(p)) return p;
  }
  return null;
}

function scriptExists(name) {
  return scriptPath(name) !== null;
}

// ── Gate definitions ────────────────────────────────────────────────────────
// Each returns a result object. Each must be checkable without asking an agent.

const GATES = {
  spec: {
    label: "Spec exists, has testable acceptance criteria, and you approved it",
    check(state) {
      const path = artifact(state, "spec.md");
      if (!existsSync(path)) {
        return FAIL_(`No spec at ${path}`, "Write the spec: problem, scope, acceptance criteria.");
      }
      const text = readFileSync(path, "utf8");
      const criteria = (text.match(/^\s*[-*]\s*\[[ x]\]/gm) || []).length;
      if (criteria === 0) {
        return FAIL_(
          "Spec has no acceptance criteria",
          "Add a checklist: `- [ ] <observable, testable outcome>`"
        );
      }
      if (!state.approvals?.spec) {
        return FAIL_(
          `Spec has ${criteria} criteria but you haven't approved it`,
          "Read it, then: node gate.mjs --advance"
        );
      }
      return PASS(`Spec approved with ${criteria} acceptance criteria`);
    },
  },

  design: {
    label: "Design notes exist (UI features only)",
    check(state) {
      if (config.skipPhases?.includes("design")) return SKIP("design is in config.skipPhases");
      if (state.skipDesign) return SKIP("marked as non-UI at run start");
      const path = artifact(state, "design.md");
      if (!existsSync(path)) {
        return FAIL_(
          `No design notes at ${path}`,
          'Non-UI feature? Re-start with --no-design, or add "design" to config.skipPhases.'
        );
      }
      return PASS("Design notes present");
    },
  },

  plan: {
    label: "Plan has discrete tasks, each naming a file",
    check(state) {
      const path = artifact(state, "plan.md");
      if (!existsSync(path)) {
        return FAIL_(`No plan at ${path}`, "Break the spec into tasks, each naming a file to change.");
      }
      const text = readFileSync(path, "utf8");
      const tasks = text.match(/^\s*[-*]\s*\[[ x]\]/gm) || [];
      if (tasks.length === 0) {
        return FAIL_("Plan has no task checkboxes", "Use `- [ ] <task>` per task.");
      }
      // A task without a file path is a wish, not a plan.
      const lines = text.split(/\r?\n/).filter((l) => /^\s*[-*]\s*\[[ x]\]/.test(l));
      const withoutPath = lines.filter((l) => !/[\w-]+\.\w{1,5}\b|`[^`]+`/.test(l));
      if (withoutPath.length > 0) {
        return FAIL_(
          `${withoutPath.length} of ${lines.length} tasks name no file`,
          `First: ${withoutPath[0].trim().slice(0, 70)}`
        );
      }
      return PASS(`Plan has ${tasks.length} tasks, all naming files`);
    },
  },

  api: {
    label: "Every external API the plan touches has fresh docs",
    check(state) {
      if (!config.apis?.length) return SKIP("no APIs declared in config.apis");
      if (!scriptExists("api-check.mjs")) {
        return UNAVAILABLE(
          "api-check.mjs not built yet",
          `${config.apis.length} API(s) declared — docs are NOT being verified.`
        );
      }
      const r = runCommand(`node ${scriptPath("api-check.mjs")} --json`);
      if (!r.ok) return FAIL_("api-check reported stale or missing docs", r.out.slice(0, 300));
      return PASS("All declared API docs are fresh");
    },
  },

  tdd: {
    label: "Tests exist and pass",
    check() {
      const testCmd = getCommand(config, "test");
      if (!testCmd) {
        return UNAVAILABLE(
          "No commands.test in config",
          "Set it in .agent/config.json — this gate cannot verify anything without it."
        );
      }
      const testFiles = findTestFiles();
      if (testFiles === 0) {
        return FAIL_(
          "No test files found",
          "TDD means tests before implementation. Write a failing test first."
        );
      }
      const r = runCommand(testCmd);
      if (!r.ok) {
        const tail = r.out.trim().split(/\r?\n/).slice(-12).join("\n");
        return FAIL_(`\`${testCmd}\` failed`, tail);
      }
      return PASS(`\`${testCmd}\` passed (${testFiles} test files found)`);
    },
  },

  review: {
    label: "Fresh-context reviewer found no blocking issues",
    check(state) {
      if (!scriptExists("review.mjs")) {
        return UNAVAILABLE(
          "reviewer not built yet",
          "Code is NOT being independently reviewed. Review it yourself before merging."
        );
      }
      const path = artifact(state, "review.json");
      if (!existsSync(path)) return FAIL_("No review findings", "Run the reviewer first.");
      let findings;
      try {
        findings = JSON.parse(readFileSync(path, "utf8"));
      } catch {
        return FAIL_("review.json is not valid JSON");
      }
      const blocking = (findings.findings || []).filter((f) => f.severity === "BLOCKING");
      if (blocking.length) {
        return FAIL_(
          `${blocking.length} blocking finding(s)`,
          blocking.map((f) => `• ${f.rule || "?"}: ${f.message}`).join("\n")
        );
      }
      return PASS("No blocking findings");
    },
  },

  pr: {
    label: "Lint, typecheck, security, and changelog all clear",
    check() {
      const checks = [];
      let failed = null;

      for (const name of ["lint", "typecheck"]) {
        const cmd = getCommand(config, name);
        if (!cmd) {
          checks.push(`${name}: ${c.dim("not configured, skipped")}`);
          continue;
        }
        const r = runCommand(cmd);
        checks.push(`${name}: ${r.ok ? c.green("pass") : c.red("FAIL")}`);
        if (!r.ok && !failed) {
          failed = FAIL_(`\`${cmd}\` failed`, r.out.trim().split(/\r?\n/).slice(-12).join("\n"));
        }
      }

      if (scriptExists("security-check.mjs")) {
        const r = runCommand(`node ${scriptPath("security-check.mjs")} --auto-only`);
        checks.push(`security: ${r.ok ? c.green("pass") : c.red("FAIL")}`);
        if (!r.ok && !failed) failed = FAIL_("security-check found failures", r.out.slice(0, 400));
      } else {
        checks.push(`security: ${c.yellow("UNAVAILABLE (not built)")}`);
      }

      const changelogOk = existsSync("CHANGELOG.md") && hasRecentChangelogEntry();
      checks.push(`changelog: ${changelogOk ? c.green("pass") : c.red("FAIL")}`);
      if (!changelogOk && !failed) {
        failed = FAIL_("No changelog entry for today", "Add one to CHANGELOG.md before opening the PR.");
      }

      if (failed) return { ...failed, detail: checks.join("\n") + "\n\n" + (failed.detail || "") };
      return PASS("All PR checks passed", checks.join("\n"));
    },
  },
};

function findTestFiles() {
  const patterns = /\.(test|spec)\.\w+$|^test_.*\.py$|_test\.(go|py|rb)$/;
  let count = 0;
  const skip = new Set(["node_modules", ".git", "dist", "build", ".next", ".agent", "agent-os"]);
  const walk = (dir) => {
    let entries;
    try {
      entries = readdirSync(dir, { withFileTypes: true });
    } catch {
      return;
    }
    for (const e of entries) {
      if (e.name.startsWith(".") || skip.has(e.name)) continue;
      const full = join(dir, e.name);
      if (e.isDirectory()) walk(full);
      else if (patterns.test(e.name)) count++;
    }
  };
  for (const d of config.sourceDirs?.length ? config.sourceDirs : ["."]) {
    if (existsSync(d)) walk(d);
  }
  // tests often live outside sourceDirs
  for (const d of ["test", "tests", "__tests__"]) if (existsSync(d)) walk(d);
  return count;
}

function hasRecentChangelogEntry() {
  const today = new Date().toISOString().slice(0, 10);
  const text = readFileSync("CHANGELOG.md", "utf8");
  return text.includes(today);
}

// ── Commands ────────────────────────────────────────────────────────────────

if (hasFlag("--list")) {
  console.log(c.bold("Pipeline gates\n"));
  GATE_ORDER.forEach((g, i) => {
    console.log(`  ${i + 1}. ${c.cyan(g.padEnd(8))} ${GATES[g].label}`);
  });
  process.exit(0);
}

const startDesc = getArg("--start");
if (startDesc) {
  const slug = slugify(startDesc);
  const state = {
    slug,
    description: startDesc,
    started: new Date().toISOString(),
    currentGate: "spec",
    passed: [],
    approvals: {},
    skipDesign: hasFlag("--no-design"),
  };
  mkdirSync(join(RUN_DIR, slug), { recursive: true });
  saveState(state);
  console.log(c.green(`✓ Run started: ${startDesc}`));
  console.log(`  Artifacts: ${join(RUN_DIR, slug)}/`);
  console.log(`  First gate: ${c.cyan("spec")} — write ${join(RUN_DIR, slug, "spec.md")}`);
  process.exit(0);
}

const state = loadState();

if (hasFlag("--status")) {
  if (!state) {
    console.log("No active run. Start one: node gate.mjs --start \"<feature>\"");
    process.exit(0);
  }
  console.log(c.bold(`Run: ${state.description}`));
  console.log(c.dim(`  ${join(RUN_DIR, state.slug)}/\n`));
  for (const g of GATE_ORDER) {
    const done = state.passed.includes(g);
    const current = g === state.currentGate;
    const mark = done ? c.green("✓") : current ? c.cyan("▶") : c.dim("·");
    const label = done ? c.dim(g) : current ? c.bold(g) : c.dim(g);
    console.log(`  ${mark} ${label}`);
  }
  process.exit(0);
}

if (!state) fail('No active run. Start one: node gate.mjs --start "<feature>"');

if (hasFlag("--advance")) {
  const g = state.currentGate;
  // Spec approval is a human act — --advance is how you give it.
  if (g === "spec") state.approvals.spec = true;
  const result = GATES[g].check(state);
  if (result.status === "FAIL") {
    console.log(c.red(`✗ Cannot advance — ${g} gate failed:`) + ` ${result.reason}`);
    if (result.detail) console.log(c.dim(result.detail));
    process.exit(1);
  }
  if (!state.passed.includes(g)) state.passed.push(g);
  const idx = GATE_ORDER.indexOf(g);
  const next = GATE_ORDER[idx + 1];
  state.currentGate = next || "done";
  saveState(state);
  console.log(c.green(`✓ ${g} passed`) + (result.reason ? c.dim(` — ${result.reason}`) : ""));
  if (next) console.log(`  Next gate: ${c.cyan(next)} — ${GATES[next].label}`);
  else console.log(c.bold("\n🎉 All gates passed. Ship it."));
  process.exit(0);
}

// Check a gate: named argument, or --next for the current one.
const named = process.argv.slice(2).find((a) => GATE_ORDER.includes(a));
const target = named || (hasFlag("--next") ? state.currentGate : state.currentGate);

if (!GATES[target]) fail(`Unknown gate "${target}". Run --list to see them.`);

const result = GATES[target].check(state);

if (JSON_MODE) {
  console.log(JSON.stringify({ gate: target, ...result }, null, 2));
  process.exit(result.status === "FAIL" ? 1 : 0);
}

const icon = {
  PASS: c.green("✓ PASS"),
  FAIL: c.red("✗ FAIL"),
  SKIP: c.dim("- SKIP"),
  UNAVAILABLE: c.yellow("⚠ UNAVAILABLE"),
}[result.status];

console.log(`${icon}  ${c.bold(target)} — ${GATES[target].label}`);
console.log(`  ${result.reason}`);
if (result.detail) {
  console.log("");
  for (const line of result.detail.split("\n")) console.log(`  ${line}`);
}

if (result.status === "UNAVAILABLE") {
  console.log("");
  console.log(c.yellow("  This gate cannot verify anything right now. It is NOT passing —"));
  console.log(c.yellow("  it simply has no checker. Verify this manually before shipping."));
}

process.exit(result.status === "FAIL" ? 1 : 0);
