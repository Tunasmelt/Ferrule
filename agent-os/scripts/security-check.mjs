#!/usr/bin/env node
// security-check.mjs — Pre-launch security gate.
//
// Three tiers, deliberately separated so coverage is never overstated:
//   UNIVERSAL   work on any stack (secrets, git hygiene, dependency audit)
//   LANGUAGE    pattern packs per language; unknown stack says so explicitly
//   MANUAL      business-logic items no script can verify — never auto-passed
//
// A security tool that implies coverage it doesn't have is worse than no tool.
//
// Usage:
//   node security-check.mjs               full report incl. manual checklist
//   node security-check.mjs --auto-only   automated checks only (for gates)
//   node security-check.mjs --json        machine-readable

import { existsSync, readFileSync, readdirSync, statSync } from "node:fs";
import { join, extname } from "node:path";
import { execSync } from "node:child_process";
import { loadConfig, getCommand, c, hasFlag, handleHelp } from "./lib/config.mjs";

handleHelp(`
security-check.mjs — pre-launch security checks

Usage:
  node security-check.mjs [--auto-only] [--json]

Exit code 1 if any automated check FAILs. WARN does not block.
Manual checklist items are never auto-passed — they need your eyes.
`);

const config = loadConfig();
const JSON_MODE = hasFlag("--json");
const AUTO_ONLY = hasFlag("--auto-only");

const results = [];
const add = (status, id, message, detail) => results.push({ status, id, message, detail });

// ── File walking ────────────────────────────────────────────────────────────

const SKIP_DIRS = new Set([
  "node_modules", ".git", "dist", "build", ".next", "out", "target",
  "__pycache__", ".venv", "venv", "vendor", "coverage", ".agent", "agent-os",
]);

const TEXT_EXT = new Set([
  ".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs", ".vue", ".svelte",
  ".py", ".go", ".rs", ".rb", ".java", ".kt", ".php", ".cs", ".swift",
  ".json", ".yml", ".yaml", ".toml", ".env", ".sh", ".sql",
]);

function walk(dir, out = []) {
  let entries;
  try {
    entries = readdirSync(dir, { withFileTypes: true });
  } catch {
    return out;
  }
  for (const e of entries) {
    if (SKIP_DIRS.has(e.name)) continue;
    const full = join(dir, e.name);
    if (e.isDirectory()) {
      if (e.name.startsWith(".") && e.name !== ".github") continue;
      walk(full, out);
    } else if (TEXT_EXT.has(extname(e.name)) || e.name.startsWith(".env")) {
      out.push(full);
    }
  }
  return out;
}

const files = walk(".");
const sourceFiles = files.filter((f) => !f.includes(".env"));

function readSafe(f) {
  try {
    if (statSync(f).size > 2_000_000) return "";
    return readFileSync(f, "utf8");
  } catch {
    return "";
  }
}

function grepFiles(regex, fileList = sourceFiles) {
  const hits = [];
  for (const f of fileList) {
    const text = readSafe(f);
    if (!text) continue;
    const lines = text.split(/\r?\n/);
    for (let i = 0; i < lines.length; i++) {
      if (regex.test(lines[i])) {
        hits.push({ file: f, line: i + 1, text: lines[i].trim().slice(0, 100) });
        if (hits.length >= 20) return hits;
      }
      regex.lastIndex = 0;
    }
  }
  return hits;
}

function run(cmd) {
  try {
    return { ok: true, out: execSync(cmd, { stdio: ["ignore", "pipe", "pipe"], encoding: "utf8" }) };
  } catch (err) {
    return { ok: false, out: (err.stdout || "") + (err.stderr || "") };
  }
}

// ═══ UNIVERSAL CHECKS — apply to every stack ════════════════════════════════

// 1. Hardcoded secrets in source.
{
  const SECRET_PATTERNS = [
    /\bsk_live_[A-Za-z0-9]{10,}/,
    /\bsk-[A-Za-z0-9]{20,}/,
    /\bAIza[A-Za-z0-9_\-]{30,}/,
    /\bghp_[A-Za-z0-9]{30,}/,
    /\bxox[baprs]-[A-Za-z0-9-]{10,}/,
    /-----BEGIN (RSA |EC |OPENSSH |PGP )?PRIVATE KEY-----/,
    /\bAKIA[0-9A-Z]{16}\b/,
  ];
  const hits = [];
  for (const re of SECRET_PATTERNS) hits.push(...grepFiles(re));
  if (hits.length) {
    add("FAIL", "hardcoded-secrets", `${hits.length} likely hardcoded secret(s) in source`,
      hits.slice(0, 5).map((h) => `${h.file}:${h.line}  ${h.text}`).join("\n") +
      "\n\nRotate these keys — they are compromised the moment they are committed.");
  } else {
    add("PASS", "hardcoded-secrets", "No hardcoded secret patterns found in source");
  }
}

// 2. .env tracked by git, and .gitignore coverage.
{
  if (!existsSync(".git")) {
    add("WARN", "git-secrets", "Not a git repo — cannot check tracked files");
  } else {
    const tracked = run("git ls-files");
    const envTracked = tracked.ok
      ? tracked.out.split(/\r?\n/).filter((f) => /(^|\/)\.env(\.|$)/.test(f) && !/\.example$/.test(f))
      : [];
    if (envTracked.length) {
      add("FAIL", "git-secrets", `.env file(s) tracked by git: ${envTracked.join(", ")}`,
        "Every key inside is compromised. Rotate them, then purge from history (git filter-repo / BFG).");
    } else {
      const gi = existsSync(".gitignore") ? readFileSync(".gitignore", "utf8") : "";
      if (/^\.env/m.test(gi)) add("PASS", "git-secrets", ".env is gitignored and untracked");
      else add("WARN", "git-secrets", ".env not tracked, but .gitignore doesn't exclude it",
        "Add `.env*` to .gitignore before someone commits one.");
    }
  }
}

// 3. Dependency vulnerabilities — uses the project's own declared audit command.
{
  const auditCmd = getCommand(config, "audit");
  if (!auditCmd) {
    add("WARN", "dependency-scan", "No commands.audit configured — dependencies not scanned",
      'Set one in .agent/config.json, e.g. "audit": "npm audit --audit-level=high".');
  } else {
    const r = run(auditCmd);
    if (r.ok) add("PASS", "dependency-scan", `\`${auditCmd}\` found no blocking vulnerabilities`);
    else add("FAIL", "dependency-scan", `\`${auditCmd}\` reported vulnerabilities`,
      r.out.trim().split(/\r?\n/).slice(-15).join("\n"));
  }
}

// 4. Security headers / HTTPS enforcement.
{
  const hits = grepFiles(/Strict-Transport-Security|Content-Security-Policy|X-Frame-Options|X-Content-Type-Options/i);
  if (hits.length) {
    add("PASS", "security-headers", `Security header config found (${hits.length} reference(s))`);
  } else {
    add("WARN", "security-headers", "No security headers configured",
      "Add CSP / HSTS / X-Frame-Options via middleware, server config, or your host.");
  }
}

// ═══ LANGUAGE-SPECIFIC PACKS ════════════════════════════════════════════════
// Explicit about coverage: an unknown stack must not look clean.

const PACKS = {
  javascript: "js", typescript: "js",
  python: "py", go: "go", ruby: "rb", php: "php", java: "java", rust: "rs",
};

const pack = PACKS[config.language];

if (!pack) {
  add("WARN", "language-pack", `No security pattern pack for "${config.language}"`,
    "Only universal checks ran. Injection, validation, and hashing were NOT checked.");
} else {
  // SQL injection: string interpolation inside a query call.
  const injectionPatterns = {
    js: /\.(query|execute|raw)\s*\(\s*[`'"].{0,200}?(\$\{|"\s*\+|'\s*\+)/,
    py: /(execute|executemany)\s*\(\s*f?["'][^"']*(%s|\{|\+)/,
    go: /(Query|Exec)\s*\(\s*(fmt\.Sprintf|"[^"]*"\s*\+)/,
    rb: /(where|execute|find_by_sql)\s*\(?\s*["'][^"']*#\{/,
    php: /(query|exec)\s*\(\s*["'][^"']*\$/,
    java: /(createQuery|executeQuery)\s*\(\s*"[^"]*"\s*\+/,
    rs: /query\s*\(\s*&?format!/,
  };
  const injHits = grepFiles(injectionPatterns[pack]);
  if (injHits.length) {
    add("FAIL", "sql-injection", `${injHits.length} possible string-interpolated quer(y/ies)`,
      injHits.slice(0, 5).map((h) => `${h.file}:${h.line}  ${h.text}`).join("\n") +
      "\n\nUse parameterised queries. Verify each — some may be safe.");
  } else {
    add("PASS", "sql-injection", "No string-interpolated queries detected");
  }

  // Input validation library present.
  const validators = {
    js: /\b(zod|yup|joi|superstruct|valibot|class-validator|ajv)\b/,
    py: /\b(pydantic|marshmallow|cerberus|voluptuous)\b/,
    go: /\b(validator|ozzo-validation)\b/,
    rb: /\b(dry-validation|activemodel)\b/,
    php: /\b(respect\/validation|symfony\/validator)\b/,
    java: /\b(javax\.validation|jakarta\.validation|hibernate-validator)\b/,
    rs: /\b(validator|garde)\b/,
  };
  const manifests = files.filter((f) =>
    /package\.json|requirements\.txt|pyproject\.toml|go\.mod|Gemfile|composer\.json|pom\.xml|Cargo\.toml/.test(f)
  );
  const valHits = [...grepFiles(validators[pack], manifests), ...grepFiles(validators[pack])];
  if (valHits.length) add("PASS", "input-validation", "Schema validation library in use");
  else add("WARN", "input-validation", "No schema validation library detected",
    "Validate request bodies and user input against a schema before use.");

  // Password hashing — only relevant if the codebase handles passwords itself.
  const touchesPasswords = grepFiles(/\bpassword\b/i).length > 0;
  if (!touchesPasswords) {
    add("PASS", "password-hashing", "No password handling found — not applicable");
  } else {
    const hashers = {
      js: /\b(bcrypt|argon2|scrypt|@node-rs\/argon2)\b/,
      py: /\b(bcrypt|argon2|passlib|werkzeug\.security)\b/,
      go: /\b(bcrypt|argon2|scrypt)\b/,
      rb: /\b(bcrypt|argon2)\b/,
      php: /password_hash|\bbcrypt\b|\bargon2\b/,
      java: /\b(BCrypt|Argon2|PBKDF2)\b/,
      rs: /\b(bcrypt|argon2|scrypt)\b/,
    };
    if (grepFiles(hashers[pack]).length) {
      add("PASS", "password-hashing", "Password hashing library in use");
    } else {
      add("FAIL", "password-hashing", "Password handling found with no hashing library",
        "Never store or compare plaintext passwords. Use bcrypt or argon2.");
    }
  }

  // Dangerous rendering (XSS) — JS only, where it's a distinct footgun.
  if (pack === "js") {
    const xss = grepFiles(/dangerouslySetInnerHTML|\.innerHTML\s*=|v-html/);
    if (xss.length) {
      add("WARN", "xss-risk", `${xss.length} raw HTML injection site(s)`,
        xss.slice(0, 5).map((h) => `${h.file}:${h.line}  ${h.text}`).join("\n") +
        "\n\nEach must sanitise user content (e.g. DOMPurify) or be provably static.");
    } else {
      add("PASS", "xss-risk", "No raw HTML injection sites found");
    }
  }
}

// ═══ MANUAL CHECKLIST — never auto-passed ═══════════════════════════════════

const MANUAL = [
  ["public-db-key", "Client uses the public/anon DB key — never the service-role key"],
  ["row-level-security", "RLS policies enabled on every table holding user data"],
  ["server-side-auth", "Auth enforced server-side; no client-only checks"],
  ["record-access", "Users can only read/write their own records"],
  ["field-tampering", "Server recomputes privileged fields (price, role, balance) — never trusts the client"],
  ["encrypt-sensitive", "Sensitive fields encrypted at rest (PII, tokens, financial data)"],
  ["rate-limit-auth", "Login/signup endpoints rate-limited specifically, not just the general API"],
  ["escape-user-content", "User-generated content escaped before render"],
  ["trim-api-responses", "API responses return only needed fields — no internal columns leaked"],
];

// ═══ OUTPUT ═════════════════════════════════════════════════════════════════

const counts = {
  PASS: results.filter((r) => r.status === "PASS").length,
  WARN: results.filter((r) => r.status === "WARN").length,
  FAIL: results.filter((r) => r.status === "FAIL").length,
};

if (JSON_MODE) {
  console.log(JSON.stringify({
    language: config.language,
    languagePackAvailable: Boolean(pack),
    summary: counts,
    results,
    manual: MANUAL.map(([id, message]) => ({ id, message, status: "MANUAL" })),
  }, null, 2));
  process.exit(counts.FAIL > 0 ? 1 : 0);
}

console.log(c.bold("Security check"));
console.log("─".repeat(60));
console.log(c.dim(`stack: ${config.language} · ${sourceFiles.length} source files scanned`));
console.log("");

for (const r of results) {
  const icon = { PASS: c.green("✓ PASS"), WARN: c.yellow("⚠ WARN"), FAIL: c.red("✗ FAIL") }[r.status];
  console.log(`${icon}  ${c.bold(r.id)}`);
  console.log(`        ${r.message}`);
  if (r.detail) for (const line of r.detail.split("\n")) console.log(c.dim(`        ${line}`));
  console.log("");
}

console.log(`${c.green(counts.PASS + " pass")}  ${c.yellow(counts.WARN + " warn")}  ${c.red(counts.FAIL + " fail")}`);

if (!pack) {
  console.log("");
  console.log(c.yellow(`⚠ Coverage is partial. No pattern pack for "${config.language}" —`));
  console.log(c.yellow("  injection, validation, and password checks did NOT run."));
}

if (!AUTO_ONLY) {
  console.log("");
  console.log(c.bold("Manual review — no script can verify these"));
  console.log("─".repeat(60));
  for (const [id, message] of MANUAL) {
    console.log(`${c.cyan("?")}  ${c.bold(id)}`);
    console.log(`        ${message}`);
  }
  console.log("");
  console.log(c.dim("These are never auto-passed. Walk them yourself before launch —"));
  console.log(c.dim("they are the highest-severity items precisely because they need judgement."));
}

console.log("");
if (counts.FAIL > 0) {
  console.log(c.red(`${counts.FAIL} automated check(s) failed — resolve before shipping.`));
  process.exit(1);
}
console.log(c.green("No automated failures.") + c.dim(` ${MANUAL.length} manual items still need your review.`));
process.exit(0);
