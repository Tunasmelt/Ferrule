// lib/claims.mjs
// A tiny, file-based mutex so Claude Code (orchestrator) and Codex (dispatched
// worker) never pick up the same docs/PHASES.md milestone at the same time.
// No daemon, no lock server — just a JSON file both sides read and write.

import { existsSync, readFileSync, writeFileSync, mkdirSync } from "node:fs";
import { join, dirname } from "node:path";
import { AGENT_DIR } from "./config.mjs";

export const ORCH_DIR = join(AGENT_DIR, "orchestration");
export const CLAIMS_PATH = join(ORCH_DIR, "claims.json");
export const LOG_DIR = join(ORCH_DIR, "logs");

function ensureDirs() {
  mkdirSync(ORCH_DIR, { recursive: true });
  mkdirSync(LOG_DIR, { recursive: true });
}

export function loadClaims() {
  if (!existsSync(CLAIMS_PATH)) return {};
  try {
    return JSON.parse(readFileSync(CLAIMS_PATH, "utf8"));
  } catch {
    throw new Error(`${CLAIMS_PATH} is corrupt JSON — fix or delete it by hand.`);
  }
}

function saveClaims(claims) {
  ensureDirs();
  writeFileSync(CLAIMS_PATH, JSON.stringify(claims, null, 2) + "\n");
}

/**
 * Claim a milestone for an owner. Throws if it's already in_progress under a
 * different owner — callers must surface that as a hard stop, never override it.
 * @returns {object} the claim record just written
 */
export function claim(milestone, owner, note = "") {
  const claims = loadClaims();
  const existing = claims[milestone];
  if (existing && existing.status === "in_progress" && existing.owner !== owner) {
    throw new Error(
      `Milestone "${milestone}" is already claimed by "${existing.owner}" ` +
        `(started ${existing.startedAt}). Release it first or pick another milestone.`
    );
  }
  const record = {
    milestone,
    owner,
    status: "in_progress",
    startedAt: new Date().toISOString(),
    endedAt: null,
    note,
  };
  claims[milestone] = record;
  saveClaims(claims);
  return record;
}

/** Mark a claimed milestone done or failed. Safe to call even if unclaimed. */
export function release(milestone, status = "done", note = "") {
  const claims = loadClaims();
  const existing = claims[milestone];
  const record = {
    ...(existing || { milestone, owner: "unknown", startedAt: null }),
    status,
    endedAt: new Date().toISOString(),
    note: note || existing?.note || "",
  };
  claims[milestone] = record;
  saveClaims(claims);
  return record;
}

export function getClaim(milestone) {
  return loadClaims()[milestone] || null;
}

export function listClaims() {
  return loadClaims();
}

/** Path for a fresh dispatch log file, timestamped so runs never collide. */
export function newLogPath(milestone, owner) {
  ensureDirs();
  const stamp = new Date().toISOString().replace(/[:.]/g, "-");
  return join(LOG_DIR, `${milestone}--${owner}--${stamp}.jsonl`);
}
