#!/usr/bin/env node
// bootstrap.mjs — Scaffold the .agent/ workspace for a project.
// Detects the stack to PROPOSE config values; never hardcodes them. Everything
// written here is a plain file you own and edit directly afterwards.
//
// Usage:
//   node bootstrap.mjs                 interactive
//   node bootstrap.mjs --yes           accept all detected defaults
//   node bootstrap.mjs --force         overwrite an existing config.json

import { existsSync, mkdirSync, writeFileSync, readFileSync } from "node:fs";
import { join } from "node:path";
import { createInterface } from "node:readline/promises";
import { stdin, stdout } from "node:process";
import { c, hasFlag, handleHelp, AGENT_DIR, CONFIG_PATH } from "./lib/config.mjs";

handleHelp(`
bootstrap.mjs — scaffold the .agent/ workspace

Usage:
  node bootstrap.mjs [--yes] [--force]

  --yes     accept detected defaults without prompting
  --force   overwrite an existing .agent/config.json
`);

const AUTO = hasFlag("--yes");
const FORCE = hasFlag("--force");
const today = new Date().toISOString().slice(0, 10);

// ── Stack detection — proposes, never decides ───────────────────────────────
// Each entry: how to recognise the ecosystem, and the commands that ecosystem
// conventionally uses. The user confirms or overrides every one of these.

function readJson(path) {
  try {
    return JSON.parse(readFileSync(path, "utf8"));
  } catch {
    return null;
  }
}

function detectStack() {
  // Node / JS / TS
  if (existsSync("package.json")) {
    const pkg = readJson("package.json") || {};
    const scripts = pkg.scripts || {};
    const deps = { ...(pkg.dependencies || {}), ...(pkg.devDependencies || {}) };
    const pm = existsSync("pnpm-lock.yaml")
      ? "pnpm"
      : existsSync("yarn.lock")
        ? "yarn"
        : "npm";
    const run = (s) => (pm === "npm" ? `npm run ${s}` : `${pm} ${s}`);
    const cmds = {};
    if (scripts.test) cmds.test = pm === "npm" ? "npm test" : `${pm} test`;
    if (scripts.lint) cmds.lint = run("lint");
    if (scripts.build) cmds.build = run("build");
    if (deps.typescript) cmds.typecheck = "npx tsc --noEmit";
    cmds.audit = `${pm} audit`;
    return {
      language: deps.typescript ? "typescript" : "javascript",
      commands: cmds,
      sourceDirs: ["src", "app"].filter((d) => existsSync(d)),
      packages: Object.keys(deps),
    };
  }
  // Python
  if (existsSync("pyproject.toml") || existsSync("requirements.txt")) {
    return {
      language: "python",
      commands: { test: "pytest", lint: "ruff check .", audit: "pip-audit" },
      sourceDirs: ["src", "app"].filter((d) => existsSync(d)),
      packages: [],
    };
  }
  // Go
  if (existsSync("go.mod")) {
    return {
      language: "go",
      commands: { test: "go test ./...", lint: "go vet ./...", build: "go build ./..." },
      sourceDirs: ["."],
      packages: [],
    };
  }
  // Rust
  if (existsSync("Cargo.toml")) {
    return {
      language: "rust",
      commands: {
        test: "cargo test",
        lint: "cargo clippy",
        build: "cargo build",
        audit: "cargo audit",
      },
      sourceDirs: ["src"],
      packages: [],
    };
  }
  return { language: "unknown", commands: {}, sourceDirs: [], packages: [] };
}

// ── API detection: proposes entries for config.apis ─────────────────────────
// Deliberately a *suggestion* layer. config.apis is the source of truth so this
// works identically on stacks where we can't introspect dependencies.

const KNOWN_APIS = [
  [/^stripe$/, "Stripe", "https://docs.stripe.com/api"],
  [/^@supabase\//, "Supabase", "https://supabase.com/docs"],
  [/^@anthropic-ai\//, "Anthropic", "https://docs.claude.com/en/api"],
  [/^openai$/, "OpenAI", "https://platform.openai.com/docs/api-reference"],
  [/^@google\/(genai|generative-ai)$/, "Google Gemini", "https://ai.google.dev/gemini-api/docs"],
  [/^twilio$/, "Twilio", "https://www.twilio.com/docs/usage/api"],
  [/^resend$/, "Resend", "https://resend.com/docs/api-reference"],
  [/^@clerk\//, "Clerk", "https://clerk.com/docs"],
];

function detectApis(packages) {
  const found = new Map();
  for (const pkg of packages) {
    for (const [re, name, docs] of KNOWN_APIS) {
      if (re.test(pkg) && !found.has(name)) found.set(name, { name, docs, pkg });
    }
  }
  // Env-var prefixes catch HTTP-only APIs that have no SDK at all.
  for (const envFile of [".env", ".env.example", ".env.local"]) {
    if (!existsSync(envFile)) continue;
    const txt = readFileSync(envFile, "utf8");
    for (const [prefix, name, docs] of [
      ["STRIPE_", "Stripe", "https://docs.stripe.com/api"],
      ["SUPABASE_", "Supabase", "https://supabase.com/docs"],
      ["ANTHROPIC_", "Anthropic", "https://docs.claude.com/en/api"],
      ["OPENAI_", "OpenAI", "https://platform.openai.com/docs/api-reference"],
      ["GEMINI_", "Google Gemini", "https://ai.google.dev/gemini-api/docs"],
      ["MINIMAX_", "MiniMax", ""],
      ["ELEVENLABS_", "ElevenLabs", ""],
      ["REPLICATE_", "Replicate", ""],
      ["TWILIO_", "Twilio", "https://www.twilio.com/docs/usage/api"],
      ["RESEND_", "Resend", "https://resend.com/docs/api-reference"],
    ]) {
      if (new RegExp(`^${prefix}`, "m").test(txt) && !found.has(name)) {
        found.set(name, { name, docs });
      }
    }
  }
  return [...found.values()];
}

// ── Prompting ───────────────────────────────────────────────────────────────

let rl;
async function ask(question, fallback) {
  if (AUTO) return fallback;
  rl ??= createInterface({ input: stdin, output: stdout });
  const shown = fallback ? ` ${c.dim(`[${fallback}]`)}` : "";
  const answer = (await rl.question(`${c.yellow("?")} ${question}${shown}: `)).trim();
  return answer || fallback;
}

// ── File writers — never clobber an existing file ────────────────────────────

const created = [];
function write(path, content) {
  if (existsSync(path)) return false;
  mkdirSync(join(path, "..") === path ? "." : path.split(/[/\\]/).slice(0, -1).join("/") || ".", {
    recursive: true,
  });
  writeFileSync(path, content);
  created.push(path);
  return true;
}

// ── Main ────────────────────────────────────────────────────────────────────

console.log(c.bold("\nagent-os bootstrap\n"));

if (existsSync(CONFIG_PATH) && !FORCE) {
  console.log(`${CONFIG_PATH} already exists. Use --force to overwrite.`);
  process.exit(0);
}

const stack = detectStack();
console.log(`Detected stack: ${c.cyan(stack.language)}`);
if (Object.keys(stack.commands).length) {
  for (const [k, v] of Object.entries(stack.commands)) {
    console.log(`  ${k.padEnd(10)} ${c.dim(v)}`);
  }
} else {
  console.log(c.yellow("  No commands detected — you'll need to fill these in."));
}

const detectedApis = detectApis(stack.packages);
if (detectedApis.length) {
  console.log(`Detected APIs: ${c.cyan(detectedApis.map((a) => a.name).join(", "))}`);
}
console.log("");

const defaultName =
  readJson("package.json")?.name ||
  process.cwd().split(/[/\\]/).filter(Boolean).pop() ||
  "project";

const name = await ask("Project name", defaultName);
const testCmd = await ask("Test command", stack.commands.test || "");
const lintCmd = await ask("Lint command", stack.commands.lint || "");

const config = {
  name,
  language: stack.language,
  commands: {
    ...stack.commands,
    ...(testCmd ? { test: testCmd } : {}),
    ...(lintCmd ? { lint: lintCmd } : {}),
  },
  rules: [],
  sourceDirs: stack.sourceDirs.length ? stack.sourceDirs : ["."],
  jargon: `${AGENT_DIR}/JARGON.md`,
  apis: detectedApis,
  skipPhases: [],
  maxReviewRounds: 3,
  staleApiDays: 30,
  memoryIndexMaxLines: 60,
};

rl?.close();

// ── Scaffold ────────────────────────────────────────────────────────────────

for (const dir of [
  AGENT_DIR,
  join(AGENT_DIR, "memory", "decisions"),
  join(AGENT_DIR, "memory", "patterns"),
  join(AGENT_DIR, "memory", "knowledge"),
  join(AGENT_DIR, "memory", "blockers"),
  join(AGENT_DIR, "memory", "transcripts"),
  join(AGENT_DIR, "api-docs"),
  join(AGENT_DIR, "rules"),
  join(AGENT_DIR, "run"),
]) {
  mkdirSync(dir, { recursive: true });
}

writeFileSync(CONFIG_PATH, JSON.stringify(config, null, 2) + "\n");
created.push(CONFIG_PATH);

write(
  join(AGENT_DIR, "memory", "index.md"),
  `# Memory index — ${name}

Layer 1 of 3. Read this file in full every turn — it is small on purpose.
Never bulk-read decisions/, patterns/, knowledge/, or blockers/. Open one
topic file only when its pointer line below is relevant to the current task.
transcripts/ is Layer 3 — never read automatically, grep only.

Format: \`DATE | TYPE | summary (<=150 chars) | -> path\`
Append-only. Run memory-consolidate.mjs to merge duplicates; don't hand-delete.

---

${today} | decision | Bootstrapped agent-os workspace | -> memory/decisions/bootstrap.md
`
);

write(
  join(AGENT_DIR, "memory", "decisions", "bootstrap.md"),
  `# Decision: bootstrap agent-os workspace

**Date:** ${today}
**Type:** decision

Standardised context, memory, and quality gates for this project.
Stack detected as \`${stack.language}\`.
`
);

write(
  join(AGENT_DIR, "JARGON.md"),
  `# Project jargon — ${name}

Terms this project uses in a specific way. Read every turn alongside
memory/index.md. Keep it short — this is vocabulary, not documentation.

Say the term, not the paragraph.

| Term | Means |
|------|-------|
| _(example)_ | _Replace these rows with your project's real vocabulary._ |
`
);

write(
  join(AGENT_DIR, "FEATURES.md"),
  `# Features — ${name}

One block per feature. Status: planned | in-progress | tested | shipped

## [FEAT-001] Example feature
**Status:** planned
**Acceptance criteria:**
- [ ] Replace this with a real, testable criterion

**Files:** _(paths this feature touches)_
`
);

write(
  join(AGENT_DIR, "rules", "README.md"),
  `# Rule files

The reviewer reads every file listed in \`config.rules\`. Add rule files here
and register them in .agent/config.json, e.g.:

    "rules": [".agent/rules/style.md", ".agent/rules/security.md"]

Write rules as checkable statements — the reviewer must be able to cite one.
Good: "Every exported function has an explicit return type."
Bad:  "Write clean code."
`
);

write(
  "CHANGELOG.md",
  `# Changelog — ${name}

## ${today}
- Bootstrapped agent-os workspace
`
);

// ── .gitignore: transcripts are local noise, everything else is committed ────
const GITIGNORE_LINE = ".agent/memory/transcripts/";
if (existsSync(".gitignore")) {
  const gi = readFileSync(".gitignore", "utf8");
  if (!gi.includes(GITIGNORE_LINE)) {
    writeFileSync(".gitignore", gi.replace(/\n*$/, "\n") + GITIGNORE_LINE + "\n");
  }
} else {
  write(".gitignore", GITIGNORE_LINE + "\n");
}

// ── Report ──────────────────────────────────────────────────────────────────

console.log(c.green(`\n✓ Workspace created (${created.length} files)\n`));
for (const f of created) console.log(`  ${f}`);

const missing = ["test", "lint"].filter((k) => !config.commands[k]);
console.log(c.bold("\nNext:"));
let step = 1;
console.log(`  ${step++}. Fill in ${AGENT_DIR}/JARGON.md with your project's vocabulary`);
console.log(`  ${step++}. Add rule files to ${AGENT_DIR}/rules/ and list them in config.rules`);
if (missing.length) {
  console.log(
    c.yellow(
      `  ${step++}. Set commands.${missing.join(" and commands.")} in ${CONFIG_PATH} — gates need them`
    )
  );
}
if (config.apis.length) {
  console.log(
    `  ${step++}. Run api-check to fetch live docs for: ${config.apis.map((a) => a.name).join(", ")}`
  );
}
console.log("");
