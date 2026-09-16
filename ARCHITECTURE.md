# Ferrule — Architecture

**Version:** 0.2
**Deployment target:** Render
**Stack:** Next.js · FastAPI · Python · Postgres · Go (proxy only)

---

## 1. Control plane / data plane split

The single most consequential structural decision.

- **Control plane** holds specs, artifacts, workflow definitions, run metadata,
  users, policy. Never sees customer payloads or raw credentials.
- **Data plane** executes plans, brokers credentials, proxies outbound traffic,
  touches real data.

*Plain language: the part that decides what should happen is separated from the
part that touches sensitive data. That is what makes a customer-hosted data
plane possible later without a rewrite.*

Cheap to do on day one. Expensive to retrofit.

```
┌───────────────── CONTROL PLANE (Render, Ferrule workspace) ─────────────────┐
│  web (Next.js, public)                                                      │
│     └─► api (FastAPI, public) ──┬── compiler-svc   (private)                │
│                                 ├── registry-svc   (private)                │
│                                 ├── workflow-svc   (private)                │
│                                 └── policy-svc     (private)                │
│                                        │                                    │
│               Render Postgres  ────────┘                                    │
│               Object storage (S3/Supabase Storage): artifacts, fixtures,    │
│                                                     traces                  │
└────────────────────────────────┬────────────────────────────────────────────┘
                                 │ signed dispatch + artifact push
┌────────────────────────────────▼──────────── DATA PLANE ────────────────────┐
│  orchestrator (private)                                                     │
│     └─► worker pool (private) ─► plan interpreter                           │
│                 │                                                           │
│                 │  every outbound call                                      │
│                 ▼                                                           │
│          egress-proxy (Go, PRIVATE SERVICE — no public URL)                 │
│             · verifies artifact signature                                   │
│             · re-derives expected request from plan                         │
│             · injects credential                                            │
│             · captures redacted traffic                                     │
│                 │                                                           │
│                 ▼                                                           │
│           external API                                                      │
│                 │                                                           │
│      run journal (Postgres) ──► drift-observer (private, async)             │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 2. Services

| Service | Render type | Language | Responsibility |
|---|---|---|---|
| `web` | Web Service (public) | Next.js | Review UI, traces. **Not in v1** |
| `api` | Web Service (public) | FastAPI | Auth, REST surface, validation |
| `compiler-svc` | Private Service | Python | Ingest → extract → generate → verify |
| `registry-svc` | Private Service | Python | Artifact storage, versioning, signing, diff |
| `workflow-svc` | Private Service | Python | Graph defs, port-type validation, pinning |
| `policy-svc` | Private Service | Python | RBAC, approval gates, capability policy |
| `orchestrator` | Background Worker | Python | Durable scheduling, retries, state machine |
| `worker` | Background Worker | Python | Executes one step; stateless |
| `egress-proxy` | **Private Service** | **Go** | Plan-bound authorization, credential injection |
| `drift-observer` | Background Worker | Python | Shape fingerprinting, baselines |

### Why the proxy is Go and not Python

It is the highest-value security boundary in the system, it sits on the hot path
of every external call, and it must remain correct even if a worker is
compromised. A small, auditable Go service with no dependency surface is the
right call even though it breaks stack consistency. It is roughly 800–1,200
lines.

### Why the proxy is a Render Private Service

Private Services have no public URL and are reachable only by other services in
the same workspace and region. Workers can reach it; the internet cannot.

---

## 3. The plan-bound proxy

Fully specified in `SPEC.md` §4.1. Architectural notes only here.

**The proxy needs artifact access.** Options, in order of preference:

1. **Push at dispatch** — the orchestrator pushes the signed artifact to the
   proxy's local cache when a run starts. No control-plane dependency on the hot
   path. Preferred.
2. Read-only artifact mirror in the data plane.
3. Fetch-on-demand from `registry-svc`. Simplest, but couples request latency to
   control-plane availability. Acceptable for v1 with aggressive caching.

**The proxy needs the step input.** It re-renders templates itself rather than
trusting the worker, so step inputs must be journaled **before** the outbound
call. The worker sends `step_input_digest`; the proxy reads the journal row and
verifies the digest matches.

**Rendering must be canonical and deterministic.** Sorted query parameters,
normalized header casing, stable JSON key ordering, no time or randomness
permitted in templates. Any non-determinism breaks the comparison and produces
false denials. This is the most likely source of early bugs — test it hard.

---

## 4. Render specifics

### 4.1 What maps cleanly

- **Private network** — same-region, same-workspace services reach each other
  over internal addresses. Everything except `web` and `api` is private.
- **Dedicated outbound IPs** (Pro plan and above) — exclusive static IPs for the
  workspace. Get these before any pilot: customers allowlisting your IPs is both
  a trust signal and frequently a security-review requirement.
- **Environment isolation** — Professional workspaces and above can block
  private network traffic entering or leaving an environment. This is the
  sandbox/production boundary.
- **Background Workers** for orchestrator, worker pool, drift observer.
- **Blueprint (`render.yaml`)** for reproducible infrastructure.

### 4.2 The honest limitation

Render provides **no per-container kernel-level egress policy**. You cannot
force a worker through the proxy at the network layer — it could open a direct
socket.

The v1 guarantee is therefore **structural, not network-enforced**: there is no
untrusted code in the worker, the interpreter executes only signed plan steps,
and every step is independently re-derived by the proxy.

This holds only while the runtime is declarative. **When a custom-code tier
arrives, its executor must leave Render** for Fly Machines, E2B, or a cluster
with NetworkPolicy. Do not run untrusted code on a PaaS.

### 4.3 Other Render notes

- Size the worker service to avoid cold starts blowing the interpreter latency
  target; the relaxed 300 ms budget in `SPEC.md` §9 assumes this.
- Artifacts, fixtures and traces go to **external object storage**, never a
  Render service disk.
- Render Postgres is fine for v1. The run journal is the write-heavy table;
  watch it first when scaling.

---

## 5. Data model

Multi-tenant via `org_id` on every row plus row-level security.

```sql
orgs(id, name, plan, created_at)
users(id, org_id, email, role)
workspaces(id, org_id, name, env)              -- sandbox | production

api_sources(id, org_id, name, base_url, auth_kind, spec_status)
source_documents(id, api_source_id, kind, sha256, blob_key, uploaded_by)
                                                -- openapi | prose_doc | example_payload
extracted_specs(id, api_source_id, version, blob_key, confidence, created_at)
spec_claims(id, extracted_spec_id, path, claim, source_doc_id, source_span)

node_defs(id, org_id, slug, display_name, execution_class)
node_versions(
  id, node_def_id, semver, artifact_hash, status,
  plan_blob_key, input_schema, output_schema,
  capability_manifest, side_effect_profile, runtime_limits, reliability_policy,
  provenance, plan_coverage, signature, approved_by, approved_at, created_at
)                       -- status: draft|proposed|approved|quarantined|retired

verification_runs(id, node_version_id, kind, passed, evidence_blob_key)
                                       -- static | mock | sandbox | permission_probe
fixtures(id, node_version_id, name, request_blob_key, response_blob_key, redacted)

workflows(id, workspace_id, name, current_version)
workflow_versions(id, workflow_id, semver, graph_json, created_at)
                  -- graph_json references artifact_hash, NEVER slug

runs(id, workflow_version_id, workspace_id, status, trigger_payload_key,
     started_at, ended_at, idempotency_key)
run_steps(id, run_id, node_version_id, seq, status,
          input_key, input_digest,          -- digest written BEFORE the call
          output_key, started_at, ended_at, failure_class, attempt)
run_events(id, run_id, seq, kind, payload)   -- append-only

credentials(id, workspace_id, api_source_id, kind, broker_ref)
             -- broker_ref only; secret material never lands in Postgres

drift_baselines(id, node_version_id, state, observation_count,
                distinct_contexts, fingerprint_blob_key, updated_at)
                                    -- state: learning|baselined
drift_observations(id, node_version_id, observed_at, diff_json, severity, confirmed)
drift_patches(id, drift_observation_id, proposed_node_version_id, status)
```

Two points worth defending:

**`graph_json` references artifact hashes, not slugs.** This is what makes
"approved means pinned" true.

**`spec_claims` exists so review is fast.** Without source spans a reviewer must
re-read the documentation to check an inference; with them they click a claim
and see the sentence.

---

## 6. Build vs buy

| Component | Decision | Reasoning |
|---|---|---|
| Durable execution | **Build** on Postgres + explicit state machine | Cheapest start, you own it, adequate to the v1 ceiling of 20 concurrent runs. Design the journal so Temporal stays possible later. |
| Expression language | **Adopt CEL** | Non-Turing-complete by design, cost limits built in, maintained Python implementation. Changed from 0.1's hand-rolled interpreter. |
| Proxy | **Build in Go** | Envoy + ext_authz is more correct but the plan-bound re-derivation logic is custom anyway, so most of Envoy's value is unused. |
| Object storage | **Buy** (S3 or Supabase Storage) | No reason to build. |
| Signing | Local ed25519 key in v1 → **KMS** at second contributor | Key custody matters as soon as it isn't just you. |
| Auth | **Buy** (Supabase Auth or Clerk) | Not the interesting problem. |

---

## 7. What is not in v1

Deferred, deliberately, with the reason:

| Deferred | Why |
|---|---|
| Visual canvas | The buyer already has orchestration. Value is the artifact, not the boxes. |
| Prose/PDF spec extraction | Noisiest, most research-heavy ingest path. Prove the rest first. |
| Writes and compensation | Security order. But see `SPEC.md` §10 — this is the weak commercial test. |
| Custom-code tier | Collapses the Render security story. Gated on the coverage number. |
| Runtime LLM nodes | Not needed to prove the thesis. |
| Drift detection (alerting) | Ships in learning mode only; detection needs mature baselines. |
| Candidate patch generation | Depends on detection. |
| Self-hosted data plane | The split makes it possible; nobody has asked yet. |
| Enterprise RBAC, SSO, audit export | No buyer yet. |
