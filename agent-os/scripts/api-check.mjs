#!/usr/bin/env node
// api-check.mjs — Verify API docs are fetched and current before integration work.
//
// An AI's knowledge of an external API is frozen at its training cutoff. APIs
// are not. Endpoints get deprecated, signatures change, model IDs get retired.
// This gate makes "fetch the real docs first" a mechanical requirement rather
// than a good intention.
//
// config.apis is the SOURCE OF TRUTH. Detection only proposes — that's what
// makes this work identically on Node, Python, Go, and Rust projects.
//
// Usage:
//   node api-check.mjs                  freshness status for every declared API
//   node api-check.mjs --detect         propose APIs found in this project
//   node api-check.mjs --scaffold       create doc stubs for declared APIs
//   node api-check.mjs --show <name>    print one cached doc
//   node api-check.mjs --json           machine-readable (gate consumes this)

import { existsSync, readFileSync, writeFileSync, mkdirSync } from "node:fs";
import { join } from "node:path";
import {
  loadConfig, c, hasFlag, getArg, handleHelp, AGENT_DIR, fail,
} from "./lib/config.mjs";

handleHelp(`
api-check.mjs — verify live API docs before writing integration code

Usage:
  node api-check.mjs [--detect] [--scaffold] [--show <name>] [--json]

  (no flags)   freshness status for every API in config.apis
  --detect     scan the project and propose APIs to add to config.apis
  --scaffold   create .agent/api-docs/<slug>.md stubs for declared APIs
  --show NAME  print a cached doc
  --json       machine-readable

Exit code 1 if any declared API has a stale or missing doc.
`);

const config = loadConfig();
const JSON_MODE = hasFlag("--json");
const DOCS_DIR = join(AGENT_DIR, "api-docs");
const STALE_DAYS = config.staleApiDays ?? 30;
const today = new Date().toISOString().slice(0, 10);

const slugify = (s) => s.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "");

// ── Version resolution: real parsing, never regex ───────────────────────────
// The bash version scraped package.json with grep+sed and reported "vitest run"
// as Stripe's version. Parse the actual structure instead.

function readJson(path) {
  try {
    return JSON.parse(readFileSync(path, "utf8"));
  } catch {
    return null;
  }
}

function resolveVersion(pkg) {
  if (!pkg) return null;

  // Node: installed version is authoritative, declared range is the fallback.
  const installed = readJson(join("node_modules", pkg, "package.json"));
  if (installed?.version) return installed.version;

  const manifest = readJson("package.json");
  if (manifest) {
    const deps = {
      ...(manifest.dependencies || {}),
      ...(manifest.devDependencies || {}),
      ...(manifest.peerDependencies || {}),
    };
    if (deps[pkg]) return deps[pkg];
  }

  // Python: requirements.txt lines like `anthropic==0.27.0`
  if (existsSync("requirements.txt")) {
    for (const line of readFileSync("requirements.txt", "utf8").split(/\r?\n/)) {
      const m = line.match(/^\s*([A-Za-z0-9._-]+)\s*([=<>~!]=+)\s*([^\s;#]+)/);
      if (m && m[1].toLowerCase() === pkg.toLowerCase()) return m[3];
      if (/^\s*([A-Za-z0-9._-]+)\s*$/.test(line) && line.trim().toLowerCase() === pkg.toLowerCase()) {
        return "unpinned";
      }
    }
  }

  // Go: go.mod require lines
  if (existsSync("go.mod")) {
    for (const line of readFileSync("go.mod", "utf8").split(/\r?\n/)) {
      const m = line.trim().match(/^(?:require\s+)?(\S+)\s+(v\S+)/);
      if (m && m[1].includes(pkg)) return m[2];
    }
  }

  // Rust: Cargo.toml `name = "1.2.3"` or `name = { version = "1.2.3" }`
  if (existsSync("Cargo.toml")) {
    for (const line of readFileSync("Cargo.toml", "utf8").split(/\r?\n/)) {
      const m = line.match(/^\s*([A-Za-z0-9_-]+)\s*=\s*(?:"([^"]+)"|\{[^}]*version\s*=\s*"([^"]+)")/);
      if (m && m[1] === pkg) return m[2] || m[3];
    }
  }

  return null;
}

// ── Detection: proposes entries, never authoritative ────────────────────────

const KNOWN = [
  [/^stripe$/, "Stripe", "https://docs.stripe.com/api"],
  [/^@supabase\//, "Supabase", "https://supabase.com/docs"],
  [/^@anthropic-ai\/|^anthropic$/, "Anthropic", "https://docs.claude.com/en/api"],
  [/^openai$/, "OpenAI", "https://platform.openai.com/docs/api-reference"],
  [/^@google\/(genai|generative-ai)$|^google-generativeai$/, "Google Gemini", "https://ai.google.dev/gemini-api/docs"],
  [/^twilio$/, "Twilio", "https://www.twilio.com/docs/usage/api"],
  [/^resend$/, "Resend", "https://resend.com/docs/api-reference"],
  [/^@clerk\//, "Clerk", "https://clerk.com/docs"],
  [/^@sendgrid\//, "SendGrid", "https://www.twilio.com/docs/sendgrid/api-reference"],
];

const ENV_HINTS = [
  ["STRIPE_", "Stripe", "https://docs.stripe.com/api"],
  ["SUPABASE_", "Supabase", "https://supabase.com/docs"],
  ["ANTHROPIC_", "Anthropic", "https://docs.claude.com/en/api"],
  ["OPENAI_", "OpenAI", "https://platform.openai.com/docs/api-reference"],
  ["GEMINI_", "Google Gemini", "https://ai.google.dev/gemini-api/docs"],
  ["MINIMAX_", "MiniMax", ""],
  ["ELEVENLABS_", "ElevenLabs", ""],
  ["REPLICATE_", "Replicate", ""],
  ["DEEZER_", "Deezer", ""],
  ["SPOTIFY_", "Spotify", "https://developer.spotify.com/documentation/web-api"],
];

function detect() {
  const found = new Map();

  const manifest = readJson("package.json");
  const pkgs = manifest
    ? Object.keys({ ...(manifest.dependencies || {}), ...(manifest.devDependencies || {}) })
    : [];
  for (const p of pkgs) {
    for (const [re, name, docs] of KNOWN) {
      if (re.test(p) && !found.has(name)) found.set(name, { name, docs, pkg: p });
    }
  }

  for (const f of ["requirements.txt", "go.mod", "Cargo.toml", "Gemfile"]) {
    if (!existsSync(f)) continue;
    const text = readFileSync(f, "utf8");
    for (const [re, name, docs] of KNOWN) {
      const bare = re.source.replace(/[\^$@\\\/]|\.\*/g, "").split("|")[0];
      if (bare && new RegExp(bare, "i").test(text) && !found.has(name)) {
        found.set(name, { name, docs });
      }
    }
  }

  // Env prefixes catch HTTP-only APIs with no SDK at all — the case that
  // dependency scanning structurally cannot find.
  for (const envFile of [".env", ".env.example", ".env.local"]) {
    if (!existsSync(envFile)) continue;
    const text = readFileSync(envFile, "utf8");
    for (const [prefix, name, docs] of ENV_HINTS) {
      if (new RegExp(`^${prefix}`, "m").test(text) && !found.has(name)) {
        found.set(name, { name, docs });
      }
    }
  }

  return [...found.values()];
}

// ── Doc freshness ───────────────────────────────────────────────────────────

function docStatus(api) {
  const path = join(DOCS_DIR, `${slugify(api.name)}.md`);
  if (!existsSync(path)) {
    return { api: api.name, path, state: "MISSING", reason: "no cached doc" };
  }
  const text = readFileSync(path, "utf8");
  const m = text.match(/^verified:\s*(\S+)/m);
  const verified = m?.[1];

  if (!verified || verified === "PENDING") {
    return { api: api.name, path, state: "PENDING", reason: "stub not filled in — no verified date" };
  }
  const when = Date.parse(verified);
  if (Number.isNaN(when)) {
    return { api: api.name, path, state: "PENDING", reason: `unparseable verified date "${verified}"` };
  }
  const ageDays = Math.floor((Date.now() - when) / 86400000);
  if (ageDays > STALE_DAYS) {
    return { api: api.name, path, state: "STALE", reason: `verified ${ageDays}d ago (limit ${STALE_DAYS}d)`, ageDays };
  }
  return { api: api.name, path, state: "FRESH", reason: `verified ${ageDays}d ago`, ageDays };
}

// ── Modes ───────────────────────────────────────────────────────────────────

if (hasFlag("--detect")) {
  const proposed = detect();
  const declared = new Set((config.apis || []).map((a) => a.name));
  const isNew = proposed.filter((p) => !declared.has(p.name));

  if (JSON_MODE) {
    console.log(JSON.stringify({ proposed, new: isNew }, null, 2));
    process.exit(0);
  }

  console.log(c.bold("Detected APIs") + c.dim("  (proposals — config.apis is the source of truth)"));
  console.log("─".repeat(56));
  if (!proposed.length) {
    console.log("None found in dependencies or .env files.");
    process.exit(0);
  }
  for (const p of proposed) {
    const mark = declared.has(p.name) ? c.green("declared") : c.yellow("NOT declared");
    console.log(`  ${p.name.padEnd(16)} ${mark}  ${c.dim(p.docs || "no docs url known")}`);
  }
  if (isNew.length) {
    console.log("");
    console.log(`Add to ${c.cyan(".agent/config.json")} under "apis":`);
    console.log(c.dim(JSON.stringify(isNew, null, 2)));
  }
  process.exit(0);
}

if (hasFlag("--scaffold")) {
  const apis = config.apis || [];
  if (!apis.length) {
    console.log("No APIs declared in config.apis. Run --detect to find candidates.");
    process.exit(0);
  }
  mkdirSync(DOCS_DIR, { recursive: true });
  let created = 0;
  for (const api of apis) {
    const path = join(DOCS_DIR, `${slugify(api.name)}.md`);
    if (existsSync(path)) continue;
    const version = api.pkg ? resolveVersion(api.pkg) : null;
    writeFileSync(path, `---
api: ${api.name}
${api.pkg ? `sdk: ${api.pkg}\n` : ""}version: ${version || "unknown"}
verified: PENDING
docs: ${api.docs || "TODO — find the official docs URL"}
---

## Version in use
${api.pkg ? `${api.pkg}@${version || "unknown"}` : "HTTP API — no SDK"}

## Endpoints / methods used in this project
- [method] — [verified signature and required fields]

## Breaking changes and gotchas verified
- [anything that changed recently vs older versions]

## Model strings / API identifiers
<!-- For AI APIs this is the highest-value section. Model IDs get retired on a
     schedule no training data keeps up with. Record the EXACT current string
     verified against live docs — never one recalled from memory. -->
- [exact current identifier]
`);
    created++;
    console.log(`  ${c.green("+")} ${path}`);
  }
  console.log("");
  console.log(created ? `${created} stub(s) created.` : "All declared APIs already have docs.");
  console.log(c.dim("Fetch the live docs, fill each stub in, then set verified: to today's date."));
  process.exit(0);
}

const showName = getArg("--show");
if (showName) {
  const path = join(DOCS_DIR, `${slugify(showName)}.md`);
  if (!existsSync(path)) fail(`No cached doc at ${path}`);
  const st = docStatus({ name: showName });
  const banner = { FRESH: c.green, STALE: c.yellow, PENDING: c.yellow, MISSING: c.red }[st.state];
  console.log(banner(`${st.state} — ${st.reason}`));
  console.log("─".repeat(56));
  console.log(readFileSync(path, "utf8"));
  process.exit(st.state === "FRESH" ? 0 : 1);
}

// ── Default: status of every declared API ───────────────────────────────────

const apis = config.apis || [];
const statuses = apis.map(docStatus);
const blocking = statuses.filter((s) => s.state !== "FRESH");

if (JSON_MODE) {
  console.log(JSON.stringify({
    declared: apis.length,
    staleDays: STALE_DAYS,
    fresh: statuses.filter((s) => s.state === "FRESH").length,
    blocking: blocking.length,
    statuses,
  }, null, 2));
  process.exit(blocking.length ? 1 : 0);
}

console.log(c.bold("API doc freshness") + c.dim(`  (stale after ${STALE_DAYS}d)`));
console.log("─".repeat(56));

if (!apis.length) {
  console.log("No APIs declared in config.apis.");
  console.log(c.dim("Run --detect to scan this project for candidates."));
  process.exit(0);
}

for (const s of statuses) {
  const icon = {
    FRESH: c.green("✓ FRESH  "),
    STALE: c.yellow("⚠ STALE  "),
    PENDING: c.yellow("⚠ PENDING"),
    MISSING: c.red("✗ MISSING"),
  }[s.state];
  console.log(`${icon}  ${s.api.padEnd(16)} ${c.dim(s.reason)}`);
}

console.log("");
if (blocking.length) {
  console.log(c.yellow(`${blocking.length} API(s) need verification before integration work.`));
  console.log("");
  console.log("For each one:");
  console.log("  1. Fetch the official docs for the version actually installed");
  console.log(`  2. Record endpoints, signatures, and model IDs in ${DOCS_DIR}/`);
  console.log(`  3. Set ${c.cyan("verified: " + today)} in the doc's frontmatter`);
  process.exit(1);
}
console.log(c.green("All declared API docs are fresh."));
process.exit(0);
