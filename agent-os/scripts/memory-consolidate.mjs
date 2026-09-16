#!/usr/bin/env node
// memory-consolidate.mjs — Keep Layer 1 small. Reports duplicate pointers,
// stale topic files, and oversized summaries. NEVER deletes anything: memory
// is append-only by design, and silent deletion of a decision record is worse
// than a slightly long index.
//
// Usage:
//   node memory-consolidate.mjs                 report
//   node memory-consolidate.mjs --stale-days 90 custom staleness window
//   node memory-consolidate.mjs --json          machine-readable

import { existsSync, readFileSync, readdirSync, statSync } from "node:fs";
import { join } from "node:path";
import { loadConfig, c, hasFlag, getArg, handleHelp, AGENT_DIR, fail } from "./lib/config.mjs";

handleHelp(`
memory-consolidate.mjs — report on memory health, change nothing

Usage:
  node memory-consolidate.mjs [--stale-days N] [--json]

Reports:
  - duplicate index pointers (same topic referenced by multiple lines)
  - index summaries over the 150-char cap
  - topic files not modified in N days (default 60)
  - orphaned topic files (on disk but not referenced in index.md)
  - broken pointers (referenced in index.md but missing on disk)

Never deletes. To archive a topic: move the file to memory/transcripts/
and remove its index.md line yourself.
`);

const config = loadConfig();
const JSON_MODE = hasFlag("--json");
const STALE_DAYS = Number(getArg("--stale-days", "60"));

const MEM = join(AGENT_DIR, "memory");
const INDEX = join(MEM, "index.md");
const TYPES = ["decisions", "patterns", "knowledge", "blockers"];
const SUMMARY_CAP = 150;

if (!existsSync(INDEX)) fail(`No ${INDEX} found. Run bootstrap.mjs first.`);

// ── Parse index.md ──────────────────────────────────────────────────────────

const ENTRY_RE = /^(\d{4}-\d{2}-\d{2})\s*\|\s*([^|]+?)\s*\|\s*(.*?)\s*\|\s*->\s*(\S+)\s*$/;

const entries = readFileSync(INDEX, "utf8")
  .split(/\r?\n/)
  .map((line, i) => {
    const m = line.match(ENTRY_RE);
    return m ? { line: i + 1, date: m[1], type: m[2], summary: m[3], path: m[4] } : null;
  })
  .filter(Boolean);

// ── Checks ──────────────────────────────────────────────────────────────────

// 1. Duplicate pointers — several sessions updated the same topic.
const byPath = new Map();
for (const e of entries) {
  if (!byPath.has(e.path)) byPath.set(e.path, []);
  byPath.get(e.path).push(e);
}
const duplicates = [...byPath.entries()]
  .filter(([, list]) => list.length > 1)
  .map(([path, list]) => ({ path, count: list.length, lines: list.map((e) => e.line) }));

// 2. Oversized summaries — these defeat the token budget.
const oversized = entries
  .filter((e) => e.summary.length > SUMMARY_CAP)
  .map((e) => ({ line: e.line, length: e.summary.length, path: e.path }));

// 3. Topic files on disk.
const onDisk = new Set();
for (const type of TYPES) {
  const dir = join(MEM, type);
  if (!existsSync(dir)) continue;
  for (const f of readdirSync(dir)) {
    if (f.endsWith(".md")) onDisk.add(`memory/${type}/${f}`);
  }
}

// 4. Broken pointers — index references a file that isn't there.
const broken = [...byPath.keys()].filter((p) => !onDisk.has(p));

// 5. Orphans — file exists but nothing points at it, so it's never read.
const referenced = new Set(byPath.keys());
const orphans = [...onDisk].filter((p) => !referenced.has(p));

// 6. Stale topics.
const cutoff = Date.now() - STALE_DAYS * 86400000;
const stale = [];
for (const relPath of onDisk) {
  const abs = join(AGENT_DIR, relPath);
  if (!existsSync(abs)) continue;
  const mtime = statSync(abs).mtimeMs;
  if (mtime < cutoff) {
    stale.push({ path: relPath, daysOld: Math.floor((Date.now() - mtime) / 86400000) });
  }
}

const overCap = entries.length > config.memoryIndexMaxLines;

// ── Output ──────────────────────────────────────────────────────────────────

if (JSON_MODE) {
  console.log(
    JSON.stringify(
      {
        indexEntries: entries.length,
        cap: config.memoryIndexMaxLines,
        overCap,
        duplicates,
        oversized,
        broken,
        orphans,
        stale,
      },
      null,
      2
    )
  );
  process.exit(0);
}

console.log(c.bold("Memory consolidation report"));
console.log("─".repeat(40));
console.log(
  `index.md entries: ${entries.length} / ${config.memoryIndexMaxLines} cap` +
    (overCap ? c.yellow("  ⚠ over cap") : c.green("  ✓"))
);

const section = (title, items, render) => {
  console.log("");
  if (items.length === 0) {
    console.log(c.green(`✓ ${title}: none`));
    return;
  }
  console.log(c.yellow(`⚠ ${title}: ${items.length}`));
  for (const it of items.slice(0, 10)) console.log(`    ${render(it)}`);
  if (items.length > 10) console.log(c.dim(`    ... and ${items.length - 10} more`));
};

section("Duplicate pointers", duplicates, (d) => `${d.path} — ${d.count} lines (${d.lines.join(", ")})`);
section("Oversized summaries", oversized, (o) => `line ${o.line}: ${o.length} chars (cap ${SUMMARY_CAP}) — ${o.path}`);
section("Broken pointers (file missing)", broken, (p) => p);
section("Orphaned files (never referenced)", orphans, (p) => p);
section(`Stale topics (>${STALE_DAYS}d)`, stale, (s) => `${s.path} — ${s.daysOld}d`);

console.log("");
console.log(c.bold("This script never deletes."));
console.log(c.dim("  Merge duplicates: edit index.md so one line points at the topic."));
console.log(c.dim("  Archive a topic:  move the file to memory/transcripts/, remove its index line."));
console.log(c.dim("  Fix a broken pointer: restore the file, or remove the index line."));
