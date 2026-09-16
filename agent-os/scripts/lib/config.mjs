// lib/config.mjs
// Every script reads config through here. Nothing else may hardcode a command,
// a path, or a language assumption — that is what makes this stack-agnostic.

import { readFileSync, existsSync } from "node:fs";
import { join, resolve } from "node:path";

export const AGENT_DIR = ".agent";
export const CONFIG_PATH = join(AGENT_DIR, "config.json");

/** Defaults applied when a key is absent. Missing optional keys must never crash. */
const DEFAULTS = {
  name: "unnamed-project",
  language: "unknown",
  commands: {},
  rules: [],
  sourceDirs: ["src"],
  jargon: join(AGENT_DIR, "JARGON.md"),
  apis: [],
  skipPhases: [],
  maxReviewRounds: 3,
  staleApiDays: 30,
  memoryIndexMaxLines: 60,
};

/**
 * Load .agent/config.json, merged over defaults.
 * @param {{required?: boolean}} opts
 * @returns {object|null} config, or null when absent and not required
 */
export function loadConfig({ required = true } = {}) {
  if (!existsSync(CONFIG_PATH)) {
    if (!required) return null;
    fail(
      `No ${CONFIG_PATH} found.\n` +
        `Run: node .agent/scripts/bootstrap.mjs   (or from the skill: node bootstrap.mjs)`
    );
  }
  let raw;
  try {
    raw = JSON.parse(readFileSync(CONFIG_PATH, "utf8"));
  } catch (err) {
    fail(`${CONFIG_PATH} is not valid JSON: ${err.message}`);
  }
  return {
    ...DEFAULTS,
    ...raw,
    commands: { ...DEFAULTS.commands, ...(raw.commands || {}) },
  };
}

/**
 * Look up a declared command. Returns null when the project doesn't define it —
 * callers must skip that check and say so, never assume a default like `npm test`.
 * @returns {string|null}
 */
export function getCommand(config, name) {
  const cmd = config.commands?.[name];
  return typeof cmd === "string" && cmd.trim() ? cmd.trim() : null;
}

/** Resolve a config-relative path safely on any OS. */
export function resolvePath(...parts) {
  return resolve(join(...parts));
}

/** Read a text file, or return null if it isn't there. */
export function readIfExists(path) {
  return existsSync(path) ? readFileSync(path, "utf8") : null;
}

// ── Output helpers ───────────────────────────────────────────────────────────
// Colour only when attached to a TTY, so --json output stays clean.

const tty = process.stdout.isTTY;
const wrap = (code) => (s) => (tty ? `\u001b[${code}m${s}\u001b[0m` : s);
export const c = {
  green: wrap("0;32"),
  yellow: wrap("0;33"),
  red: wrap("0;31"),
  cyan: wrap("0;36"),
  bold: wrap("1"),
  dim: wrap("2"),
};

export function fail(msg) {
  console.error(c.red("✗ ") + msg);
  process.exit(1);
}

/** Standard --help handling. Returns true if help was printed. */
export function handleHelp(usage) {
  if (process.argv.includes("--help") || process.argv.includes("-h")) {
    console.log(usage.trim());
    process.exit(0);
  }
  return false;
}

export const hasFlag = (f) => process.argv.includes(f);

/** Read `--key value` from argv. */
export function getArg(name, fallback = null) {
  const i = process.argv.indexOf(name);
  return i !== -1 && process.argv[i + 1] ? process.argv[i + 1] : fallback;
}
