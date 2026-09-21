-- Milestone 5a: orchestrator state machine, run journal, step traces.
--
-- Deliberately single-tenant for now (no org_id/workspace_id) -- matches
-- this project's consistent scope-narrowing elsewhere (3a's compiler
-- service has no workspace auth either). workflow_version_id and
-- node_version_hash are plain string columns, not foreign keys: workflows
-- and node versions currently live in other services' in-memory stores,
-- not this database.
--
-- next_event_seq on runs exists so run_events.seq can be reserved
-- atomically (UPDATE ... RETURNING) instead of computed via
-- MAX(seq)+1, which would race under concurrent appends to the same run.

CREATE TABLE runs (
    id TEXT PRIMARY KEY,
    workflow_version_id TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('running', 'succeeded', 'failed')),
    next_event_seq INTEGER NOT NULL DEFAULT 1,
    started_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    ended_at TIMESTAMPTZ
);

CREATE TABLE run_steps (
    id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL REFERENCES runs (id),
    node_version_hash TEXT NOT NULL,
    seq INTEGER NOT NULL,
    status TEXT NOT NULL CHECK (
        status IN ('pending', 'running', 'succeeded', 'retryable_error', 'permanent_error')
    ),
    attempt INTEGER NOT NULL DEFAULT 1,
    -- SPEC.md section 7's six failure classes, exactly.
    failure_class TEXT CHECK (
        failure_class IS NULL OR failure_class IN
        ('transient', 'auth', 'schema_mismatch', 'permission_denied', 'timeout', 'rate_limited')
    ),
    next_attempt_at TIMESTAMPTZ,
    started_at TIMESTAMPTZ,
    ended_at TIMESTAMPTZ,
    UNIQUE (run_id, seq)
);

-- Append-only (CLAUDE.md: "never add an UPDATE path to run_events") --
-- enforced by convention in ferrule_orchestrator's own code (no UPDATE
-- statement anywhere targets this table), the same discipline the proxy's
-- run journal already follows.
CREATE TABLE run_events (
    id BIGSERIAL PRIMARY KEY,
    run_id TEXT NOT NULL REFERENCES runs (id),
    seq INTEGER NOT NULL,
    kind TEXT NOT NULL,
    payload JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (run_id, seq)
);
