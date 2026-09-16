#!/usr/bin/env node
// memory-sync.mjs — Session end: extract decisions and gotchas from HANDOFF.md
// into the 3-tier memory system.
//
//   Layer 1  memory/index.md      pointers only, read every turn
//   Layer 2  memory/<type>/*.md   detail, opened on demand
//   Layer 3  memory/transcripts/  full session, never read — grep only
//
// This is a token-budget mechanism. index.md must stay small no matter how
// large the project's history grows, so summaries are hard-capped and detail
// is pushed down a tier.
//
// Usage:
//   node memory-sync.mjs                    sync from HANDOFF.md
//   node memory-sync.mjs --file NOTES.md    sync from a different file
//   node memory-sync.mjs --dry-run          show what would be written
//   node memory-sync.mjs --json             machine-readable result

import { existsSync, readFileSync, writeFileSync, appendFileSync, copyFileSync, mkdirSync } from "node:fs";
import { join } from "node:path";
import { loadConfig, c, hasFlag, getArg, handleHelp, AGENT_DIR, fail } from "./lib/config.mjs";

handleHelp(`
memory-sync.mjs — extract session decisions into tiered memory

Usage:
  node memory-sync.mjs [--file HANDOFF.md] [--dry-run] [--json]

Reads "### Decisions" and "### Gotchas" sections from the source file.
Decisions become memory/decisions/*.md, gotchas become memory/blockers/*.md,
each with a one-line pointer appended to memory/index.md. The whole source
file is archived to memory/transcripts/ for later grepping.
`);

const config = loadConfig();
const DRY = hasFlag("--dry-run");
const JSON_MODE = hasFlag("--json");
const SOURCE = getArg("--file", "HANDOFF.md");

const MEM = join(AGENT_DIR, "memory");
const INDEX = join(MEM, "index.md");
const today = new Date().toISOString().slice(0, 10);
const SUMMARY_CAP = 150;

if (!existsSync(SOURCE)) {
  fail(`No ${SOURCE} found. Write a session handoff first, or pass --file <path>.`);
}
if (!existsSync(INDEX)) {
  fail(`No ${INDEX} found. Run bootstrap.mjs first.`);
}

// ── Section extraction ──────────────────────────────────────────────────────
// Bounded by the next heading of the same or higher level, so a gotcha near the
// end of the Decisions section can't leak into the wrong bucket. (This exact
// bug existed in the bash version, which used `grep -A20`.)

function extractSection(text, heading) {
  const lines = text.split(/\r?\n/);
  const out = [];
  let inSection = false;
  for (const line of lines) {
    if (/^#{1,6}\s/.test(line)) {
      const isTarget = new RegExp(`^#{1,6}\\s*${heading}\\s*$`, "i").test(line.trim());
      if (isTarget) {
        inSection = true;
        continue;
      }
      if (inSection) break; // any subsequent heading ends the section
    }
    if (inSection) {
      const m = line.match(/^\s*[-*]\s+(.*\S)\s*$/);
      if (m) out.push(m[1]);
    }
  }
  return out;
}

// ── Slug + summary helpers ──────────────────────────────────────────────────

function slugify(text) {
  const s = text
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "")
    .slice(0, 40)
    .replace(/-+$/, "");
  return s || `entry-${Date.now()}`;
}

function summarise(text) {
  const flat = text.replace(/\s+/g, " ").trim();
  return flat.length > SUMMARY_CAP ? flat.slice(0, SUMMARY_CAP - 3) + "..." : flat;
}

/** Escape pipes so a summary can't break the index table format. */
const safeForIndex = (s) => s.replace(/\|/g, "\\|");

// ── Entry writer ────────────────────────────────────────────────────────────

const written = [];
const indexLines = [];

function addEntry(type, text) {
  const slug = slugify(text);
  const relPath = `memory/${type}/${slug}.md`;
  const filePath = join(MEM, type, `${slug}.md`);

  if (existsSync(filePath)) {
    // Same topic revisited — append a dated update rather than clobbering.
    if (!DRY) {
      appendFileSync(filePath, `\n---\n**${today} update:** ${text}\n`);
    }
    written.push({ path: relPath, action: "appended" });
  } else {
    const title = text.length > 80 ? text.slice(0, 77) + "..." : text;
    const body = `# ${title}\n\n**Date:** ${today}\n**Type:** ${type}\n\n${text}\n`;
    if (!DRY) {
      mkdirSync(join(MEM, type), { recursive: true });
      writeFileSync(filePath, body);
    }
    written.push({ path: relPath, action: "created" });
  }

  indexLines.push(`${today} | ${type} | ${safeForIndex(summarise(text))} | -> ${relPath}`);
}

// ── Run ─────────────────────────────────────────────────────────────────────

const source = readFileSync(SOURCE, "utf8");
const decisions = extractSection(source, "Decisions");
const gotchas = extractSection(source, "Gotchas");

for (const d of decisions) addEntry("decisions", d);
for (const g of gotchas) addEntry("blockers", g);

let transcript = null;
if (indexLines.length > 0) {
  if (!DRY) {
    appendFileSync(INDEX, indexLines.join("\n") + "\n");
    mkdirSync(join(MEM, "transcripts"), { recursive: true });
    const stamp = new Date().toISOString().replace(/[:.]/g, "-").slice(0, 19);
    transcript = join(MEM, "transcripts", `${stamp}.md`);
    copyFileSync(SOURCE, transcript);
  } else {
    transcript = join(MEM, "transcripts", "<timestamp>.md");
  }
}

// ── Index size warning — the whole point of the tier system ─────────────────

const indexEntryCount = existsSync(INDEX)
  ? readFileSync(INDEX, "utf8").split(/\r?\n/).filter((l) => /^\d{4}-\d{2}-\d{2}\s*\|/.test(l)).length
  : 0;
const overCap = indexEntryCount > config.memoryIndexMaxLines;

// ── Output ──────────────────────────────────────────────────────────────────

if (JSON_MODE) {
  console.log(
    JSON.stringify(
      {
        synced: indexLines.length,
        decisions: decisions.length,
        gotchas: gotchas.length,
        files: written,
        transcript,
        indexEntries: indexEntryCount,
        indexOverCap: overCap,
        dryRun: DRY,
      },
      null,
      2
    )
  );
  process.exit(0);
}

if (DRY) console.log(c.yellow("DRY RUN — nothing written\n"));

if (indexLines.length === 0) {
  console.log(
    `No "### Decisions" or "### Gotchas" bullet lists found in ${SOURCE} — nothing to sync.`
  );
  console.log(c.dim(`\nExpected format:\n\n### Decisions\n- Chose X over Y because Z\n\n### Gotchas\n- W fails when V\n`));
  process.exit(0);
}

console.log(c.green(`✓ Synced ${indexLines.length} entries`) + c.dim(` (${decisions.length} decisions, ${gotchas.length} gotchas)`));
for (const w of written) {
  console.log(`  ${w.action === "created" ? "+" : "~"} ${w.path}`);
}
console.log(c.green(`✓ Session archived`) + c.dim(` -> ${transcript} (grep-only, never auto-loaded)`));

console.log(`\nindex.md: ${indexEntryCount} entries`);
if (overCap) {
  console.log(
    c.yellow(
      `⚠ Over the ${config.memoryIndexMaxLines}-entry cap. Layer 1 is read every turn — run memory-consolidate.mjs.`
    )
  );
}
