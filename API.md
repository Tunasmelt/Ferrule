# Ferrule — API Reference

**Version:** v1 (unreleased)
**Base URL:** `https://api.ferrule.dev/v1`
**Format:** JSON. `Content-Type: application/json` on all requests with a body.

Everything the CLI and (later) the canvas does goes through this API. That is
what keeps the embedded and headless paths open.

---

## Conventions

### Authentication

```
Authorization: Bearer <api_key>
```

Keys are workspace-scoped. A key for a `sandbox` workspace cannot act on a
`production` workspace.

### Idempotency

Mutating endpoints accept `Idempotency-Key`. Replaying a key within 24 hours
returns the original response without re-executing.

```
Idempotency-Key: 9f8c2a1e-...
```

Required on `POST /workflows/{id}/runs`. Optional elsewhere.

### Errors

```json
{
  "error": {
    "code": "plan_not_representable",
    "message": "Operation requires general computation not expressible in the plan language.",
    "details": { "reason": "recursive tree flattening over unbounded depth" },
    "request_id": "req_01HX..."
  }
}
```

| Status | Meaning |
|---|---|
| 400 | Malformed request |
| 401 | Missing or invalid key |
| 403 | Key lacks permission, or policy denied |
| 404 | Not found within this workspace |
| 409 | State conflict (e.g. approving an already-approved version) |
| 422 | Semantically invalid (e.g. graph references unknown hash) |
| 429 | Rate limited; `Retry-After` present |
| 500 | Internal |

### Async jobs

Compilation and verification are long-running. They return `202` with a job
handle; poll for the result.

```json
{ "job_id": "job_01HX...", "status": "queued", "poll_url": "/v1/jobs/job_01HX..." }
```

Job statuses: `queued` · `running` · `succeeded` · `failed` · `needs_input`

`needs_input` means the compiler hit an ambiguity requiring a human choice; the
response carries the options.

### Pagination

Cursor-based. `?limit=50&cursor=<opaque>`. Responses carry
`{ "data": [...], "next_cursor": "..." | null }`.

---

## API sources

### `POST /sources`

Register an API you will build nodes against.

```json
{
  "name": "Acme ERP",
  "base_url": "https://api.acme-erp.example",
  "auth_kind": "bearer"          // api_key | bearer
}
```

→ `201` `{ "id": "src_01HX...", "spec_status": "none" }`

### `POST /sources/{id}/documents`

Multipart upload. `kind` is `openapi` | `prose_doc` | `example_payload`.

In v1 only `openapi` is compiled. Other kinds are stored and hashed for
provenance, and to record what form real documentation arrives in.

→ `201` `{ "id": "doc_01HX...", "sha256": "...", "kind": "openapi" }`

### `POST /sources/{id}/extract`

Build a candidate spec from uploaded documents.

→ `202` job. On success:

```json
{
  "extracted_spec_id": "spec_01HX...",
  "confidence": 0.94,
  "operations_found": 47,
  "claims": 312
}
```

### `GET /sources/{id}/claims?path=<json_pointer>`

Extracted claims with source spans. This is what makes review fast.

```json
{
  "data": [{
    "path": "/paths/~1invoices~1{id}/get/responses/404",
    "claim": "404 body has shape { error: { message: string } }",
    "source_document_id": "doc_01HX...",
    "source_span": [142, 168],
    "confidence": 0.71
  }]
}
```

---

## Node compilation

### `POST /nodes/compile`

```json
{
  "source_id": "src_01HX...",
  "task": "Fetch a single invoice by its ID and return the invoice object",
  "execution_class": "action",
  "sandbox_credential_ref": "cred_01HX...",   // optional
  "constraints": {
    "methods": ["GET"],
    "side_effect_profile": "read_only"
  }
}
```

→ `202` job.

On `succeeded`:

```json
{
  "node_version_id": "nv_01HX...",
  "status": "proposed",
  "artifact_hash": "sha256:...",
  "plan_coverage": "representable",
  "evidence_url": "/v1/nodes/nd_01HX.../versions/1.0.0/evidence"
}
```

On `needs_input`:

```json
{
  "status": "needs_input",
  "question": "Two operations match 'fetch invoice'.",
  "options": [
    { "operation_id": "getInvoice",      "path": "/v2/invoices/{id}" },
    { "operation_id": "getInvoiceDraft", "path": "/v2/drafts/invoices/{id}" }
  ],
  "resume_url": "/v1/jobs/job_01HX.../resume"
}
```

**`plan_coverage` is always present**, including on failure. Values:
`representable` · `representable_partial` · `not_representable`.

### `POST /jobs/{id}/resume`

```json
{ "choice": "getInvoice" }
```

---

## Node versions

### `GET /nodes/{node_id}/versions/{semver}/evidence`

The reviewer bundle. The most important read endpoint in the API.

```json
{
  "artifact_hash": "sha256:...",
  "status": "proposed",
  "behaviour_summary": "Sends one GET to /v2/invoices/{invoice_id} and returns the invoice object. Routes 404 to not_found.",
  "request_preview": [{
    "step_id": "fetch",
    "method": "GET",
    "url": "https://api.acme-erp.example/v2/invoices/INV-1042",
    "headers": { "Authorization": "Bearer <redacted:acme_erp_api_key>" },
    "rendered_from": { "input": { "invoice_id": "INV-1042" } }
  }],
  "input_schema":  { "...": "..." },
  "output_schema": { "ports": { "ok": {}, "not_found": {}, "retryable_error": {}, "permanent_error": {} } },
  "capabilities": {
    "hosts": ["api.acme-erp.example"],
    "methods": ["GET"],
    "secrets": ["acme_erp_api_key"],
    "egress_default": "deny"
  },
  "side_effect_profile": "read_only",
  "assumptions": [{
    "claim": "404 body shape",
    "basis": "not documented; inferred from example payload 2",
    "source_document_id": "doc_01HX...",
    "source_span": [142, 168]
  }],
  "verification": {
    "static":     { "passed": true, "checks": ["schema_valid", "templates_bound", "cel_typechecked", "hosts_declared"] },
    "mock":       { "passed": true, "cases": 6 },
    "sandbox":    { "passed": true, "cases": 3, "account": "acme-sandbox" },
    "permission": { "passed": true, "attempted_violations": 0 }
  },
  "traces": [{ "case": "happy_path", "trace_url": "/v1/traces/tr_01HX..." }],
  "provenance": {
    "source_documents": ["sha256:..."],
    "compiler_version": "0.3.1",
    "builder_model": "<provider>/<model>@<version>",
    "prompt_version": "compile-plan-v7",
    "plan_coverage": "representable"
  }
}
```

### `POST /nodes/{node_id}/versions/{semver}/approve`

```json
{ "reviewer_note": "Checked 404 assumption against docs p.12. Correct." }
```

→ `200` with the signed artifact. `409` if already approved.

Approval is the only transition that produces a signature. After it the version
is immutable; only `status` may change thereafter.

### `GET /nodes/{node_id}/versions/{semver}/diff?against={semver}`

```json
{
  "schema_changes": [{ "port": "ok", "field": "invoice.tax_total", "change": "added", "type": "number" }],
  "plan_changes":   [{ "step": "fetch", "field": "url", "from": "/v2/...", "to": "/v3/..." }],
  "capability_changes": [],
  "breaking": true,
  "breaking_reason": "output port 'ok' gained a required field"
}
```

### `POST /nodes/{node_id}/versions/{semver}/quarantine`

```json
{ "reason": "drift_confirmed", "drift_observation_id": "drf_01HX..." }
```

Blocks new runs. In-flight runs complete — a run never switches implementation
mid-execution.

### `GET /nodes/{node_id}/versions/{semver}/artifact`

Returns the signed tarball. `Accept: application/vnd.ferrule.artifact+tar`.

Verifiable offline with the published workspace public key.

---

## Credentials

### `POST /credentials`

```json
{
  "workspace_id": "ws_01HX...",
  "source_id": "src_01HX...",
  "binding": "acme_erp_api_key",
  "kind": "bearer",
  "value": "<secret>"
}
```

→ `201` `{ "id": "cred_01HX...", "broker_ref": "brk_01HX...", "binding": "acme_erp_api_key" }`

**The value is never returned by any endpoint.** Only `broker_ref` is stored in
Postgres; secret material lives in the broker.

### `DELETE /credentials/{id}`

Revokes immediately. Any node whose plan binds to it fails `auth` on the next
run.

---

## Workflows

### `POST /workflows`

```json
{ "workspace_id": "ws_01HX...", "name": "Invoice sync" }
```

### `POST /workflows/{id}/versions`

```json
{
  "graph": {
    "nodes": [
      { "id": "n1", "artifact_hash": "sha256:aaa..." },
      { "id": "n2", "artifact_hash": "sha256:bbb..." }
    ],
    "edges": [
      { "from": "n1", "port": "ok",        "to": "n2" },
      { "from": "n1", "port": "not_found", "to": "terminal_skip" }
    ]
  }
}
```

`422` if a port type is incompatible with its target's input schema, if a hash
is unknown or unapproved, or if a node is referenced by slug.

**Nodes are referenced by `artifact_hash` only.** There is no slug form.

### `POST /workflows/{id}/runs`

`Idempotency-Key` required.

```json
{ "input": { "invoice_id": "INV-1042" } }
```

→ `202` `{ "run_id": "run_01HX...", "status": "queued" }`

### `GET /runs/{id}`

```json
{
  "run_id": "run_01HX...",
  "status": "succeeded",
  "workflow_version": "1.2.0",
  "steps": [{
    "seq": 0,
    "node_version_hash": "sha256:aaa...",
    "status": "succeeded",
    "port": "ok",
    "attempt": 1,
    "started_at": "...", "ended_at": "...",
    "input_digest": "sha256:...",
    "trace_url": "/v1/traces/tr_01HX..."
  }]
}
```

### `POST /runs/{id}/steps/{seq}/replay`

Re-runs one step against its **recorded input**.

```json
{ "mode": "recorded_response" }   // recorded_response | live
```

- `recorded_response` — deterministic, no external call, always permitted.
- `live` — calls the real API. **Rejected with 403 for any node whose
  `side_effect_profile` is not `read_only`.**

### `GET /traces/{id}`

Redacted request and response for one step.

```json
{
  "step_id": "fetch",
  "request":  { "method": "GET", "url": "...", "headers": { "Authorization": "<redacted>" } },
  "response": { "status": 200, "headers": {}, "body_shape": { "data": { "id": "string", "total": "number" } } },
  "body_retained": false
}
```

`body_shape` is a structural fingerprint. Full bodies are retained only when the
workspace has explicitly opted in.

---

## Drift

### `GET /drift/baselines?node_version_hash=`

```json
{
  "node_version_hash": "sha256:aaa...",
  "state": "learning",
  "observation_count": 41,
  "distinct_contexts": 2,
  "thresholds": { "observations": 200, "contexts": 5 },
  "detection_active": false
}
```

Detection does not run until `baselined`. This is deliberate — see
`SPEC.md` §6.1.

### `GET /drift/observations?node_version_hash=&severity=`

```json
{
  "data": [{
    "id": "drf_01HX...",
    "observed_at": "...",
    "severity": "critical",
    "confirmed": true,
    "confirmation_method": "repeated_observation",
    "diff": { "field": "data.total", "change": "type_changed", "from": "number", "to": "string", "mapped": true },
    "blast_radius": { "workflow_versions": ["wfv_01HX...", "wfv_01HY..."], "runs_last_7d": 412 }
  }]
}
```

`mapped: true` means the node's output schema reads this field — which is why it
is `critical` rather than `info`.

---

## Rate limits

| Endpoint class | Limit |
|---|---|
| Compile | 10 / hour / workspace |
| Run trigger | 100 / minute / workspace |
| Reads | 1000 / minute / workspace |

`429` responses carry `Retry-After`.

---

## Not in v1

Documented so their absence is deliberate rather than an oversight:

`POST /nodes/{id}/versions/{v}/patch` (drift-driven patch generation) ·
workflow canvas layout endpoints · prose-document compilation ·
`POST /workflows/{id}/runs` with write-class nodes · self-hosted data plane
registration · SSO and SCIM · audit log export.
