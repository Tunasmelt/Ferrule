#!/usr/bin/env node
// claim.mjs — CLI over the milestone claim ledger (lib/claims.mjs).
// Both Claude Code and any dispatched Codex run go through this before
// touching a docs/PHASES.md milestone, so two agents never work the same one.
//
// Usage:
//   node claim.mjs claim <milestone> <owner> ["note"]
//   node claim.mjs release <milestone> [done|failed] ["note"]
//   node claim.mjs status [milestone]
//   node claim.mjs --json ...          machine-readable

import { c, hasFlag, handleHelp, fail } from "./lib/config.mjs";
import { claim, release, getClaim, listClaims } from "./lib/claims.mjs";

handleHelp(`
claim.mjs — milestone claim ledger

Usage:
  node claim.mjs claim <milestone> <owner> ["note"]
  node claim.mjs release <milestone> [done|failed] ["note"]
  node claim.mjs status [milestone]

Owners are free text: "claude", "codex", or a person's name. Claiming a
milestone already in_progress under a DIFFERENT owner fails loudly — that is
the point of this file.
`);

const JSON_MODE = hasFlag("--json");
const [, , cmd, ...rest] = process.argv.filter((a) => a !== "--json");

function out(obj, human) {
  if (JSON_MODE) console.log(JSON.stringify(obj, null, 2));
  else console.log(human);
}

if (cmd === "claim") {
  const [milestone, owner, note = ""] = rest;
  if (!milestone || !owner) fail("Usage: node claim.mjs claim <milestone> <owner> [note]");
  try {
    const record = claim(milestone, owner, note);
    out(record, c.green(`✓ Claimed ${milestone} for ${owner}`));
  } catch (err) {
    if (JSON_MODE) {
      console.log(JSON.stringify({ error: err.message }, null, 2));
      process.exit(1);
    }
    fail(err.message);
  }
} else if (cmd === "release") {
  const [milestone, status = "done", note = ""] = rest;
  if (!milestone) fail("Usage: node claim.mjs release <milestone> [done|failed] [note]");
  const record = release(milestone, status, note);
  out(record, c.green(`✓ Released ${milestone} (${status})`));
} else if (cmd === "status") {
  const [milestone] = rest;
  if (milestone) {
    const record = getClaim(milestone);
    if (!record) {
      out(null, c.dim(`No claim recorded for ${milestone}.`));
    } else {
      const mark = record.status === "in_progress" ? c.yellow("● in progress") : c.dim(record.status);
      out(record, `${mark}  ${record.milestone} — ${record.owner} (since ${record.startedAt})`);
    }
  } else {
    const claims = listClaims();
    const entries = Object.values(claims);
    if (!entries.length) {
      out({}, c.dim("No claims recorded yet."));
    } else if (JSON_MODE) {
      console.log(JSON.stringify(claims, null, 2));
    } else {
      console.log(c.bold("Milestone claims\n"));
      for (const r of entries) {
        const mark =
          r.status === "in_progress" ? c.yellow("● in progress") : r.status === "failed" ? c.red("✗ failed") : c.dim("✓ done");
        console.log(`  ${mark.padEnd(24)} ${r.milestone.padEnd(10)} ${r.owner}`);
      }
    }
  }
} else {
  fail(`Unknown command "${cmd}". Run --help.`);
}
