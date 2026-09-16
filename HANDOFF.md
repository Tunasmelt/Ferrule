# Ferrule — Handoff

For whoever picks this up next, including future-you after a gap. Read this
first, then `CLAUDE.md`, then `docs/SPEC.md`.

---

## State as of this handoff

**Nothing is built.** Specification version 0.2, revised after external review.
No code, no repository scaffolding, no infrastructure.

| Artifact | State |
|---|---|
| `docs/SPEC.md` | 0.2, current |
| `docs/ARCHITECTURE.md` | 0.2, current |
| `docs/API.md` | v1 surface, designed not implemented |
| `docs/PHASES.md` | 9 phases, gates defined |
| `CLAUDE.md` | current |
| `CHANGELOG.md` | 0.1 → 0.2 recorded |
| Code | none |
| Infrastructure | none |
| Name | Ferrule — trademark and domain checks **outstanding** |

---

## The one-paragraph version

Ferrule compiles API documentation into signed, immutable integration nodes that
carry their own schemas, permissions, tests and provenance, and are monitored for
upstream change. The product is not code generation — that is commodity. It is
everything between *generated* and *trusted in production*. The core mechanism
is a proxy that independently re-derives every outbound request from the signed
plan, so a node cannot make a call its approved plan does not describe.

---

## The three things that matter most

**1. The plan-bound proxy is the product.** Everything else supports it. If you
build one thing, build phase 2. It is what makes the central claim true, and it
is cheap only because the plan language is declarative.

**2. `plan_coverage` decides the roadmap.** Every compile records whether the
operation was representable in the plan language. If that number lands below
~70% on real integrations, the declarative-first premise is wrong and the
custom-code tier becomes the main path — which breaks the Render security story
and changes the product. Instrument it from the first compile, before there is
any UI to show it in.

**3. The real competitor is a coding agent, not Zapier.** An engineer with Claude
Code, an API spec and existing CI already gets generation and tests. Ferrule wins
on brokered credentials, plan-bound enforcement, pinned versions and drift
monitoring — never on generation speed. Any benchmark must use that baseline.

---

## Decisions already made, and why

| Decision | Reason | Reversible? |
|---|---|---|
| Declarative plan, not arbitrary code | Makes the whole security story possible on a PaaS | Hard — everything depends on it |
| Proxy in Go, not Python | Highest-value security boundary, hot path, must survive worker compromise | Yes, but don't |
| CEL, not a hand-rolled evaluator | Hand-rolled expression evaluators are where safe DSLs leak | Yes |
| Enforcement (phase 2) before generation (phase 3) | Retrofitting security onto a working generator kills products in this category | Yes, but don't |
| No canvas in v1 | Buyer already has orchestration; value is the artifact | Yes |
| Render as host | Fits the stack; private services and dedicated IPs map well | Yes, until custom-code tier |
| Postgres state machine over Temporal | Cheapest start, adequate to 20 concurrent runs | Yes — journal designed to allow the swap |
| Read-only only in v1 | Security ordering | Yes, and probably should be revisited early |

---

## Decisions deliberately deferred

- **Startup vs portfolio path.** `PHASES.md` assumes portfolio-first with the
  startup option preserved. The startup path front-loads a concierge validation
  study and delays code. **Pick one before writing code** — it changes the first
  four weeks entirely.
- **Custom-code tier.** Gated on the coverage number. If it arrives, its executor
  leaves Render for Fly Machines, E2B, or a cluster with NetworkPolicy.
- **Vertical wedge.** "Implementation teams" is a function, not a reachable
  market. A single integration family (logistics status APIs, ERP invoice
  retrieval, regional commerce) would make the compiler measurably better. The
  UAE e-invoicing mandate work is a live candidate — re-verify the phasing dates,
  they move.
- **Writes.** Security order says later; commercial reality says the first paying
  conversation will need one.

---

## If you are starting today

Portfolio path, in order:

1. Repo scaffold, `render.yaml`, `make check` wired to CI
2. Phase 0 — artifact format, both languages, conformance suite
3. Phase 1 — plan language, interpreter, static checker
4. Phase 2 — the proxy, and `make security` green
5. Phase 3 — compiler on OpenAPI, and **read the coverage number**

Stop at step 5 and re-read `SPEC.md` §3.4 before continuing. That number
determines whether phases 4–8 are the right build.

Startup path: stop reading and go run the validation track in `PHASES.md`
instead. Do not write code first.

---

## Traps

- **Do not add a proxy bypass for local development.** Run a local proxy. The
  absence of a bypass is the product.
- **Do not let the worker's rendered request substitute for the proxy's own
  rendering.** Sending both is correct. Sending only the worker's defeats the
  mechanism entirely.
- **Canonicalization drift between the Python and Go implementations will cause
  false denials** that look like mysterious intermittent failures. The
  conformance suite is not optional, and it is the first thing to check when
  something inexplicable happens.
- **Do not widen drift severity to unmapped fields.** It converts the
  differentiator into an alarm nobody reads.
- **Do not build the canvas.** It will feel like progress. It is the most
  replaceable part of the system.

---

## Open risks, honestly

- Coverage below 70% invalidates the runtime choice.
- The wedge is private APIs; v1 only ingests OpenAPI, which private APIs rarely
  publish. v1 therefore tests on a population that is not quite the buyer's
  problem. Mitigation: record documentation form every time.
- Drift is the differentiator and the least-built part. It is also the piece with
  the highest chance of being too noisy to trust.
- Recruiting integration engineers who will share real documentation and sandbox
  credentials is a sales problem, and the hardest single item on the startup
  path.
- Solo-developer feasibility of the full specification is poor. Of the narrowed
  v1, reasonable.

---

## Related prior work

**Drifter** (existing project) — proxy-based regression testing for MCP tool
schemas. The observe-proxy pattern, schema diffing and severity model are
directly reusable for phase 6. Do not rebuild them from scratch; port them.

### Decisions

- Milestone 0c treats a new output field as required when its existing port has
  no explicit JSON Schema `required` array; an explicit array is authoritative.
- Artifact diffs recurse through schema properties and plan/capability objects,
  sorting ports, fields, and step IDs for deterministic output.
- Milestone 0a canonical numbers use plain decimal notation without exponents
  or insignificant zeroes; negative zero canonicalizes to zero.
- Canonical JSON is compact UTF-8 with object keys sorted by Unicode code point.

### Gotchas

- Go 1.27.1 is installed at `C:\Program Files\Go` but is not on the default
  `PATH`; prepend that directory before running Go or Make targets.
