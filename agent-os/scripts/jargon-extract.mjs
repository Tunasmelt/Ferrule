#!/usr/bin/env node
// jargon-extract.mjs — Propose domain-vocabulary candidates from the codebase.
//
// Works on any language because it reads IDENTIFIERS, not syntax. Every
// language names things in camelCase, PascalCase, or snake_case, so the same
// tokenizer works on .ts, .py, .go, .rs, .rb, .java without knowing grammar.
//
// It PROPOSES. It cannot know which words are domain jargon and which are
// generic — that judgement is yours. Nothing is written to JARGON.md without
// --write, and definitions are always left blank for you to fill in.
//
// Usage:
//   node jargon-extract.mjs                  report candidates
//   node jargon-extract.mjs --top 40         show more
//   node jargon-extract.mjs --min-files 3    only terms spread across N+ files
//   node jargon-extract.mjs --write          append new candidates to JARGON.md
//   node jargon-extract.mjs --json

import { existsSync, readFileSync, readdirSync, statSync, appendFileSync } from "node:fs";
import { join, extname, basename } from "node:path";
import { loadConfig, c, hasFlag, getArg, handleHelp, AGENT_DIR } from "./lib/config.mjs";

handleHelp(`
jargon-extract.mjs — propose domain vocabulary from your codebase

Usage:
  node jargon-extract.mjs [--top N] [--min-files N] [--write] [--json]

  --top N         how many candidates to show (default 25)
  --min-files N   only terms appearing in at least N files (default 2)
  --write         append new candidates to .agent/JARGON.md with blank definitions
  --json          machine-readable

Reads config.sourceDirs. Terms already in JARGON.md are skipped.
This proposes candidates only — you decide what's real jargon.
`);

const config = loadConfig();
const TOP = Number(getArg("--top", "25"));
const MIN_FILES = Number(getArg("--min-files", "2"));
const WRITE = hasFlag("--write");
const JSON_MODE = hasFlag("--json");

const JARGON_PATH = config.jargon || join(AGENT_DIR, "JARGON.md");

// ── What to scan ────────────────────────────────────────────────────────────

const CODE_EXT = new Set([
  ".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs", ".vue", ".svelte",
  ".py", ".go", ".rs", ".rb", ".java", ".kt", ".swift", ".cs",
  ".php", ".scala", ".ex", ".exs", ".dart", ".c", ".cpp", ".h",
  ".sql", ".graphql", ".prisma",
]);

const SKIP_DIRS = new Set([
  "node_modules", ".git", "dist", "build", ".next", "out", "target",
  "__pycache__", ".venv", "venv", "vendor", "coverage", ".agent",
  "agent-os", ".turbo", ".cache", "migrations",
]);

// ── Stopwords: generic programming vocabulary, not domain jargon ────────────
// Deliberately broad. A false negative (missing a real term) costs you nothing
// — you can add it by hand. A false positive floods the list with noise.

const STOP = new Set(`
get set add remove delete update create new init make build run start stop
handle handler on off use with without from to for by at in out into
is are has have was were be been being do does did done
data value values item items list array map set obj object props prop
type types kind class interface enum struct func function method fn
const let var static public private protected readonly async await
return yield throw catch try finally if else switch case break continue
for while loop each every some find filter reduce sort join split
string number boolean bool int float double char byte void null undefined nil none true false
name id key index idx count total sum min max first last next prev previous
error err exception fail failed success ok result response request req res
config options opts params param args arg input output
component render view page layout style styles css className
state props context provider hook ref memo callback effect
test tests spec mock stub fixture expect assert should describe it
util utils helper helpers common shared lib libs core base main app
file files path paths dir directory folder src source
api client server route routes endpoint url uri http https
default export import module require package
size length width height top bottom left right
time date now timestamp created updated deleted
user users admin
temp tmp foo bar baz qux
this self that other another
and or not all any none each
number str num arr dict tuple
i j k n m x y z a b
def pass lambda elif import global nonlocal assert del raise except
package chan defer go goto range select fallthrough
impl trait mod pub crate match where dyn unsafe extern
end module require include attr initialize nil unless until then begin ensure
extends implements abstract final synchronized volatile transient native
super constructor namespace using typedef sizeof template typename
cache payload provider providers respond hit miss log logs logger status
promise resolve reject await async meta process env environ link links
div span header footer nav section article aside button input form label
includes include contains exists valid invalid check checked verify
fetch post put patch head options body headers query params search params
token session cookie auth login logout signin signout signup register
page pages limit offset cursor cursor page_size per_page sort order
message messages text content html json xml csv
enabled disabled active inactive visible hidden open closed
mode flag flags level levels stage step steps phase
window document element node parent child children sibling
event events emit listen listener dispatch subscribe unsubscribe
mount unmount update render rerender
loading not found notfound layout template route middleware
index main entry app root global globals provider providers
public static assets styles types utils constants config configs
`.trim().split(/\s+/));

// ── Walk + tokenize ─────────────────────────────────────────────────────────

function walk(dir, files = []) {
  let entries;
  try {
    entries = readdirSync(dir);
  } catch {
    return files;
  }
  for (const entry of entries) {
    if (SKIP_DIRS.has(entry) || entry.startsWith(".")) continue;
    const full = join(dir, entry);
    let st;
    try {
      st = statSync(full);
    } catch {
      continue;
    }
    if (st.isDirectory()) walk(full, files);
    else if (CODE_EXT.has(extname(entry))) files.push(full);
  }
  return files;
}

/** Split an identifier into lowercase words. Handles camelCase, PascalCase, snake_case, kebab. */
function splitIdentifier(id) {
  return id
    .replace(/([a-z0-9])([A-Z])/g, "$1 $2")   // camelCase -> camel Case
    .replace(/([A-Z]+)([A-Z][a-z])/g, "$1 $2") // HTTPServer -> HTTP Server
    .split(/[^A-Za-z]+/)
    .map((w) => w.toLowerCase())
    .filter(Boolean);
}

/** Strip strings and comments so prose and copy don't pollute identifier counts. */
function stripNoise(src) {
  return src
    .replace(/\/\*[\s\S]*?\*\//g, " ")     // block comments
    .replace(/(^|[^:])\/\/.*$/gm, "$1 ")   // line comments (not URLs)
    .replace(/#.*$/gm, " ")                // python/ruby/shell comments
    .replace(/"""[\s\S]*?"""/g, " ")       // python docstrings
    .replace(/`[^`]*`/g, " ")              // template literals
    .replace(/"[^"\n]*"/g, " ")            // double-quoted strings
    .replace(/'[^'\n]*'/g, " ");           // single-quoted strings
}

// ── Collect ─────────────────────────────────────────────────────────────────

const sourceDirs = (config.sourceDirs?.length ? config.sourceDirs : ["."]).filter((d) =>
  existsSync(d)
);

const files = sourceDirs.flatMap((d) => walk(d));

/** word -> { count, files:Set, pathHits:number } */
const terms = new Map();

function record(word, file, fromPath = false) {
  if (word.length < 3 || word.length > 24) return;
  if (STOP.has(word)) return;
  if (/^\d+$/.test(word)) return;
  if (!terms.has(word)) terms.set(word, { count: 0, files: new Set(), pathHits: 0 });
  const t = terms.get(word);
  t.count++;
  t.files.add(file);
  if (fromPath) t.pathHits++;
}

for (const file of files) {
  let src;
  try {
    src = stripNoise(readFileSync(file, "utf8"));
  } catch {
    continue;
  }
  // Identifiers in code bodies
  for (const id of src.match(/[A-Za-z_][A-Za-z0-9_]{2,}/g) || []) {
    for (const w of splitIdentifier(id)) record(w, file);
  }
  // Words in the PATH (directories + filename) are the strongest signal —
  // people name folders and files after domain concepts, not after `slice`
  // or `href`. This is what separates vocabulary from incidental code words.
  const pathWords = file
    .split(/[/\\]/)
    .flatMap((seg) => splitIdentifier(seg.replace(/\.[^.]+$/, "").replace(/^\[|\]$/g, "")));
  for (const w of pathWords) record(w, file, true);
}

// ── Merge simple plurals ────────────────────────────────────────────────────
// "beat" and "beats" are one concept. Fold the plural into the singular when
// both exist, so the candidate list isn't half duplicates.

function singularOf(word) {
  if (word.endsWith("ies") && word.length > 4) return word.slice(0, -3) + "y";
  if (word.endsWith("ses") || word.endsWith("xes") || word.endsWith("zes")) return word.slice(0, -2);
  if (word.endsWith("s") && !word.endsWith("ss") && word.length > 3) return word.slice(0, -1);
  return null;
}

for (const [word, t] of [...terms.entries()]) {
  const singular = singularOf(word);
  if (singular && terms.has(singular)) {
    const target = terms.get(singular);
    target.count += t.count;
    target.pathHits += t.pathHits;
    for (const f of t.files) target.files.add(f);
    terms.delete(word);
  }
}

// ── Existing jargon: don't re-propose what's already defined ────────────────

const existing = new Set();
if (existsSync(JARGON_PATH)) {
  const jargonText = readFileSync(JARGON_PATH, "utf8");
  for (const line of jargonText.split(/\r?\n/)) {
    const m = line.match(/^\s*\|\s*([^|]+?)\s*\|/);
    if (m) {
      const term = m[1].replace(/[_*`]/g, "").trim().toLowerCase();
      if (term && term !== "term" && !/^-+$/.test(term)) existing.add(term);
    }
  }
}

// ── Rank ────────────────────────────────────────────────────────────────────
// Three signals, in order of trust:
//   1. pathHits  — appears in a folder/file name. People name paths after
//                  domain concepts. This is the strongest signal by far.
//   2. fileCount — spread across files. A word in 8 files is a concept;
//                  a word used 50 times in one file is a local variable.
//   3. count     — raw frequency, weakest, log-damped so it can't dominate.

const candidates = [...terms.entries()]
  .filter(([w, t]) => t.files.size >= MIN_FILES && !existing.has(w))
  .map(([word, t]) => ({
    word,
    count: t.count,
    fileCount: t.files.size,
    inPath: t.pathHits > 0,
    score:
      (t.pathHits > 0 ? 1000 + t.pathHits * 10 : 0) +
      t.files.size * Math.log2(t.count + 1),
    samples: [...t.files].slice(0, 3),
  }))
  .sort((a, b) => b.score - a.score)
  .slice(0, TOP);

// ── Output ──────────────────────────────────────────────────────────────────

if (JSON_MODE) {
  console.log(
    JSON.stringify(
      { filesScanned: files.length, existingTerms: existing.size, candidates },
      null,
      2
    )
  );
  process.exit(0);
}

console.log(c.bold("Jargon candidates"));
console.log("─".repeat(50));
console.log(
  c.dim(`scanned ${files.length} files in ${sourceDirs.join(", ")} · ${existing.size} terms already defined`)
);

if (files.length === 0) {
  console.log(
    c.yellow(
      `\nNo source files found. Check config.sourceDirs (currently: ${JSON.stringify(config.sourceDirs)}).`
    )
  );
  process.exit(0);
}

if (candidates.length === 0) {
  console.log(c.green("\nNo new candidates — either everything's defined, or try --min-files 1."));
  process.exit(0);
}

console.log("");
const wordWidth = Math.max(...candidates.map((x) => x.word.length), 4);
console.log(c.dim(`${"term".padEnd(wordWidth)}  files  uses  path  example`));
for (const x of candidates) {
  console.log(
    `${x.word.padEnd(wordWidth)}  ${String(x.fileCount).padStart(5)}  ${String(x.count).padStart(4)}  ${
      x.inPath ? c.green(" yes") : c.dim("  no")
    }  ${c.dim(x.samples[0] || "")}`
  );
}

console.log("");
console.log(c.bold("These are candidates, not jargon."));
console.log(c.dim("  path=yes means the word names a folder or file — usually a real concept."));
console.log(c.dim("  Keep a word if a teammate would use it and a stranger would misread it."));
console.log(c.dim("  Drop generic nouns, library names, and framework vocabulary."));

if (WRITE) {
  const rows = candidates.map((x) => `| ${x.word} |  |`).join("\n");
  appendFileSync(JARGON_PATH, `\n${rows}\n`);
  console.log(c.green(`\n✓ Appended ${candidates.length} rows to ${JARGON_PATH} — fill in the Means column, delete what isn't jargon.`));
} else {
  console.log(c.dim(`\n  Run with --write to append these to ${JARGON_PATH} as blank rows.`));
}
