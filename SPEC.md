# Ferrule — Technical Specification

**Version:** 0.2 (supersedes 0.1)
**Status:** pre-implementation
**Scope of this document:** what Ferrule is, what it guarantees, and what it
deliberately does not guarantee. Architecture in `ARCHITECTURE.md`, build order
in `PHASES.md`, HTTP surface in `API.md`.

---

## 1. Product statement

Ferrule turns API documentation into **verified integration nodes** — signed,
immutable artifacts that carry their own schemas, permissions, tests and
provenance, and that are monitored for upstream change after deployment.

The product is not the generator. Generating integration code is commodity.
The product is everything between *generated* and *trusted in production*:

- What exactly will this integration call?
- What is it permitted to touch, and who enforces that?
- How was it tested, and what did the tests prove?
- Who approved it, and is the deployed version the reviewed version?
- Has the upstream API changed since?

---

## 2. Guarantees

These are the claims Ferrule makes. They are deliberately narrow so they are
all defensible.

### 2.1 What Ferrule guarantees

| Guarantee | Mechanism |
|---|---|
| The approved plan is the executed plan | Content-addressed artifact; workflows reference `artifact_hash`, never a mutable slug |
| No request leaves that the plan does not describe | Proxy independently re-derives each request from the signed plan and compares (§4) |
| Generated logic never holds a reusable credential | Secrets are markers in the plan; the proxy substitutes at call time |
| Every execution is fully traced | Append-only run journal, redacted request/response capture |
| Recorded-response replay is deterministic | Fixtures replay against stored responses, not the live API |
| Every generated claim traces to a source | `spec_claims` link each extracted fact to a document span |

### 2.2 What Ferrule explicitly does not guarantee

Stating these prevents the product from writing cheques it cannot cash.

- **Identical live results across runs.** External state, time, rate limits,
  credential scope and upstream behaviour all vary. Ferrule guarantees the same
  *plan* runs, not the same *result*.
- **Bit-exact model reproducibility.** Hosted models drift beneath a version
  label. The correct phrasing is **configuration-pinned and fully traced**.
- **Network-level egress confinement on a PaaS.** See §4.4. The v1 guarantee is
  structural (no untrusted code exists in the worker), not kernel-enforced.
- **Zero-noise drift detection.** Detection is probabilistic and gated on
  baseline maturity (§6).

---

## 3. The restricted plan

The default runtime is not a programming language. It is a small, total
(non-Turing-complete) declarative format.

*Plain language: the compiler fills in a strict form describing which HTTP calls
to make and how to map the data. A form cannot loop forever, cannot reach the
disk, and cannot do anything the form has no field for.*

### 3.1 Contents

- **HTTP steps** — method, URL template, headers, query, body template
- **Mapping expressions** — CEL (see §3.3) over the step's input and response
- **Conditions** — comparisons and boolean combinators over typed fields only
- **Pagination** — `cursor` | `offset` | `link_header` | `none`
- **Response routing** — status code and body predicate → named output port

### 3.2 Explicitly absent

Arbitrary loops, recursion, filesystem access, process spawn, dynamic
evaluation, arbitrary imports, unbounded iteration.

### 3.3 Expression language

**Use CEL (Common Expression Language), not a hand-rolled evaluator and never
`eval` or Jinja with attribute access.** CEL is non-Turing-complete by design,
has built-in evaluation cost limits, and has a maintained Python implementation.
Configure: max cost per expression, no custom extension functions in v1,
strict type checking at compile time.

This is a change from spec 0.1, which proposed a hand-written interpreter.
Hand-rolled expression evaluators are where "safe" DSLs leak.

### 3.4 Coverage instrumentation — mandatory

Every compile attempt records `plan_coverage`:

```
representable        — the operation fits the plan language entirely
representable_partial— fits except for N named transformations
not_representable    — requires general computation
```

**This number decides the product.** If a large share of real integrations are
not representable, the custom-logic tier stops being a v3 nicety and becomes a
v1 requirement — and the security story changes with it. Instrument from the
first compile, before there is any UI to display it.

Target to beat: ≥ 70% `representable` on real integration tasks.

---

## 4. Security model

### 4.1 Plan-bound request authorization

This is the core security mechanism and the main change from spec 0.1.

Spec 0.1 had the proxy authorize against a coarse capability manifest — host,
method, secret binding. That is insufficient. `GET api.customer.com/*` permits
reading every endpoint on that host, which does not support the claim that a
node built to read invoices cannot reach anything else.

In 0.2, **the proxy re-derives the expected request itself and compares.**

```
worker → proxy
    { node_version_hash, run_id, step_seq, step_id,
      step_input_digest, canonicalized_request }

proxy
    1. fetch signed artifact by hash (local cache, verify signature)
    2. locate step_id within the plan; reject if absent
    3. read the recorded step input from the run journal by
       (run_id, step_seq); verify digest matches
    4. independently render that step's URL, headers, query and body
       templates from that input — the proxy does not trust the
       worker's rendering
    5. canonicalize both and compare; any divergence → DENY + security event
    6. enforce per-step request budget, redirect policy, max response
       bytes, content-type allowlist
    7. resolve secret binding → workspace credential → inject
    8. forward; capture redacted request/response for trace and drift
    9. strip secret material from the response before returning
```

The proxy is a second, adversarial implementation of the interpreter. The worker
cannot propose a request the plan does not already describe.

Path patterns, query-parameter constraints, permitted headers and body shape
constraints all fall out of this automatically and need no extra manifest
fields.

**Consequences to design for:**

- Step inputs must be journaled **before** the outbound call, so the proxy can
  re-render deterministically.
- The proxy needs read access to signed artifacts. Use a read-only artifact
  cache in the data plane, populated at dispatch time.
- Template rendering must be deterministic and canonical: sorted query params,
  normalized header casing, stable JSON key order, no time or randomness in
  templates. Any non-determinism in rendering breaks the comparison.
- Redirects are never followed cross-host. Same-host redirects count against the
  step request budget.

### 4.2 Threat model

| Threat | Control |
|---|---|
| Plan exfiltrates credentials | Secrets never enter worker memory; proxy substitutes and strips |
| Plan calls unintended endpoint | Plan-bound authorization (§4.1) |
| Prompt injection via API response data | Data grants no capability; plan is fixed at approval |
| Prompt injection via source documentation | Docs are untrusted compiler input; assumptions surfaced for review |
| Worker compromise | Enforcement is out-of-process; worker holds no durable secret |
| Cross-tenant leakage | `org_id` RLS, per-workspace credential scoping, no shared worker state |
| Log leakage | Redaction before persistence, never after |
| Replay abuse | Idempotency keys; fixture replay restricted to read-only (§6.5) |

### 4.3 Permission probe — part of verification

Before approval, every node is run against an adversarial mock that:

- returns a 302 to a different host
- returns a body far exceeding `max_output_bytes`
- returns a payload containing injection-style instructions
- returns an unexpected content type

A node that follows the redirect, accepts the oversized body, or alters
behaviour based on the injected text **fails verification**.

### 4.4 Honest limits on Render

Render provides no per-container kernel-level egress policy. A worker process
could in principle open a direct socket bypassing the proxy.

**Therefore the v1 claim is structural, not network-enforced:**

> No untrusted code runs in the worker. The interpreter executes only steps from
> a signed plan, and every step is independently re-derived and authorized by the
> proxy. There is no path by which a plan can express an unapproved request.

This holds while the runtime stays declarative. **It collapses the moment a
custom-code tier is added.** When that tier arrives, its executor must move off
Render to an environment with real isolation (Fly Machines, E2B, or a cluster
with NetworkPolicy). This is a further argument for keeping the declarative plan
the default as long as possible.

---

## 5. Node artifact

Content-addressed tarball. `artifact_hash = sha256(canonical(manifest) || plan
|| fixtures)`.

```yaml
ferrule_version: "1"

identity:
  node_id: acme-erp.get-invoice
  semver: 1.4.0
  artifact_hash: sha256:...
  compatible_with: ">=1.0.0 <2.0.0"

execution_class: action        # trigger|action|transform|condition|terminal

input_schema: { $schema: "...", type: object, required: [invoice_id] }
output_schema:
  ports:
    ok:               { type: object, properties: { invoice: {} } }
    not_found:        { type: object }
    retryable_error:  { type: object, properties: { reason: {} } }
    permanent_error:  { type: object, properties: { reason: {} } }

capabilities:
  hosts:   ["api.acme-erp.example"]
  methods: ["GET"]
  secrets: ["acme_erp_api_key"]
  egress_default: deny
  # NOTE: this block is defence-in-depth only. Primary authorization is
  # plan-bound (§4.1). The manifest never widens what the plan permits.

side_effect_profile: read_only   # read_only|reversible_write|irreversible_write|financial

runtime_limits:
  wall_time_ms: 15000
  memory_mb: 128
  max_output_bytes: 1048576
  max_requests: 5
  max_redirects: 0
  allowed_content_types: ["application/json"]

reliability:
  retry: { on: [retryable_error], max_attempts: 3, backoff: exponential, jitter: true }
  idempotency: not_required
  timeout_ms: 15000
  on_permanent_error: route

plan:
  steps:
    - id: fetch
      method: GET
      url: "https://api.acme-erp.example/v2/invoices/{{ input.invoice_id }}"
      headers: { Authorization: "Bearer {{ secret.acme_erp_api_key }}" }
      pagination: none
      expect:
        200:     { route: ok,               map: { invoice: "response.data" } }
        404:     { route: not_found,        map: { invoice_id: "input.invoice_id" } }
        429:     { route: retryable_error,  map: { reason: "'rate_limited'" } }
        5xx:     { route: retryable_error,  map: { reason: "response.error.message" } }
        default: { route: permanent_error,  map: { reason: "response.error.message" } }

provenance:
  source_documents: [sha256:..., sha256:...]
  compiler_version: "0.3.1"
  builder_model: "<provider>/<model>@<version>"
  prompt_version: "compile-plan-v7"
  parameters: { temperature: 0 }
  plan_coverage: representable
  assumptions:
    - claim: "404 body shape"
      basis: "not documented; inferred from example payload 2"
      source: { doc: sha256:..., span: [142, 168] }

verification:
  static:     { passed: true, checks: [schema_valid, templates_bound, cel_typechecked, hosts_declared] }
  mock:       { passed: true, cases: 6 }
  sandbox:    { passed: true, cases: 3, account: "acme-sandbox" }
  permission: { passed: true, attempted_violations: 0 }
  approved_by: "..."
  approved_at: "..."

signature: { alg: ed25519, key_id: "...", sig: "..." }
```

`{{ secret.* }}` never resolves in the worker. It is a marker the proxy
substitutes.

---

## 6. Drift detection

The differentiator, and the part most likely to fail by being noisy.

### 6.1 Maturity states

A node's drift monitoring progresses through states. **Detection does not run
until the baseline is mature.**

| State | Condition | Behaviour |
|---|---|---|
| `learning` | < N distinct observations, or < M distinct calling contexts | Observe and record only. No alerts. |
| `baselined` | thresholds met | Detection active |
| `at_risk` | anomaly confirmed | Alert, blast radius computed, node still runs |
| `quarantined` | high confidence + policy allows | Blocked from new runs |

v1 ships `learning` only. Detection ships in v2. A node approved on three
sandbox fixtures has no idea what normal looks like, and alerting from that
baseline is how the feature becomes a nuisance.

### 6.2 What is observed

Structural fingerprints only — field paths, types, nullability, array-ness,
enum-ish value sets. **Never values.** Cross-customer learning is permitted on
detection heuristics, never on any customer's schemas or data.

### 6.3 Severity, scoped to mapped fields

The single rule that removes most false positives:

**Severity is computed against fields the node's `output_schema` actually maps.
A change to a field nothing reads is `info`, not `critical`.**

| Signal | Severity |
|---|---|
| Mapped field removed | critical |
| Mapped field type changed | critical |
| New required field causes request rejection | high |
| Error-rate shift by status class | high |
| Enum value outside known set on a mapped field | medium |
| Unmapped field added or removed | info |

### 6.4 Known false-positive sources

Design for these explicitly: nullable fields appearing and disappearing;
different account tiers exposing different fields; arrays empty during
verification; legitimate new enum values; error-rate shifts caused by customer
configuration rather than upstream change. Mitigations: observation windows,
per-endpoint baselines, distinct-context thresholds, per-node suppression.

### 6.5 Confirmation ladder

Never quarantine on a single observation.

1. Observe anomaly
2. Confirm across multiple calls, or via a safe read-only probe
3. Compute consumer impact (which workflow versions reference this hash)
4. Alert, mark `at_risk`
5. Quarantine only on high confidence **and** explicit workspace policy

**Fixture replay against a live API is restricted to `read_only` nodes.**
Idempotency keys protect against duplicates, not against a replayed
cancellation being a legitimate cancellation.

---

## 7. Execution engine

- **Graph:** DAG. Cycles only via bounded `map` with a max-iteration limit.
- **Routing:** typed named ports. Branch conditions read schema-validated fields
  only, never free text from a model.
- **Durability:** state persisted after every transition; crash resumes from the
  journal.
- **Delivery:** at-least-once. Any node with a write side-effect profile must
  declare an idempotency strategy or workflow validation fails.
- **Version stability:** a run in flight never switches to a repaired
  implementation.

### Failure classes

| Class | Retry | Route |
|---|---|---|
| `transient` | yes, backoff + jitter | `retryable_error` after exhaustion |
| `auth` | no | `permanent_error` + credential alert |
| `schema_mismatch` | no | `permanent_error` + drift signal |
| `permission_denied` | no | `permanent_error` + security event |
| `timeout` | once | `retryable_error` |
| `rate_limited` | yes, honour `Retry-After` | `retryable_error` |

**Compensation is not rollback.** A compensating action is another external call
that can fail; it gets its own node, idempotency key and failure routing.

---

## 8. Compiler pipeline

```
ingest → extract → resolve → generate → verify → present → sign
```

| Stage | Output | Failure mode |
|---|---|---|
| ingest | stored blobs + hashes | unsupported format |
| extract | candidate spec + source-linked claims | low confidence → request more docs |
| resolve | operation sequence | ambiguous → ask user to choose |
| generate | schemas, plan, tests, coverage verdict | not representable → flag |
| verify | static, mock, sandbox, permission results | failure → regenerate, bounded attempts |
| present | reviewer evidence bundle | — |
| sign | immutable artifact | — |

**Two model roles, configured separately.** Builder model: strongest available,
temperature 0, runs once per node, quality over cost. Runtime model: cheap,
fast, pinned per node version, used only inside inference nodes (v3+). Never
share a setting between them.

**Generation is never trusted on first output.** Verify is a loop: failures are
fed back with the failure attached, bounded attempts, then surfaced to a human.

---

## 9. Non-functional targets (v1)

| Dimension | Target |
|---|---|
| Compile time, spec → evidence bundle | < 3 min p50, < 10 min p95 |
| Plan interpreter cold start | < 300 ms (relaxed from 100 ms — PaaS cold starts) |
| Proxy added latency | < 25 ms p95 (relaxed — extra artifact fetch and re-render) |
| Run step overhead, excl. external call | < 80 ms p95 |
| Durability | no run loss on worker kill; resume < 30 s |
| Concurrent runs per workspace | 20 (explicit v1 ceiling) |
| Trace retention | 30 days |
| Fixture retention | life of the node version |

Set these low and explicit. A v1 that promises 20 concurrent runs and holds
beats one that implies scale it cannot deliver.

---

## 10. Open questions

- **Plan coverage.** The number from §3.4 decides whether the custom-code tier
  is v3 or v1. Nothing else matters as much.
- **Documentation form.** The wedge is private APIs, which rarely ship OpenAPI.
  v1 ingests OpenAPI only, so record what form real docs actually arrive in
  during every pilot or test.
- **Read-only vs writes.** Read-only is the right security order but a weak
  commercial test — implementation-team pain is disproportionately writes. One
  idempotent write behind an approval gate belongs in the first pilot that has
  a paying conversation attached.
- **Coding agents are the real substitute.** An engineer with a coding agent and
  existing CI already gets generation and tests. Ferrule wins on brokered
  credentials, plan-bound enforcement, pinned versions and drift — not on
  generation speed. Benchmarks must be set against that baseline, not against
  hand-writing from scratch.
