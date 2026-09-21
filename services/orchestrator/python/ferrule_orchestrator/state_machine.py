"""Run/step state machine on Postgres (milestone 5a).

SPEC.md section 7: "state persisted after every transition; crash resumes
from the journal." Each function here commits exactly once, after both
the run_steps transition and its run_events append are staged in the same
transaction -- there is no window where one persists without the other,
so a crash between them can't leave the journal missing an event for a
real state change.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Mapping

import psycopg
from psycopg.rows import dict_row

from .failure import FailureClass, classify_and_route


@dataclass(frozen=True, slots=True)
class RunStep:
    id: str
    run_id: str
    node_version_hash: str
    seq: int
    status: str
    attempt: int
    failure_class: str | None
    next_attempt_at: datetime | None


def _append_event(conn: psycopg.Connection, run_id: str, kind: str, payload: Mapping[str, object]) -> None:
    """Append one event; does not commit. Callers own the transaction
    boundary so a step transition and its event persist atomically together.

    Reserves run_events.seq via UPDATE ... RETURNING on runs.next_event_seq
    rather than SELECT MAX(seq)+1 FROM run_events, which would race under
    concurrent appends to the same run -- the same class of bug this
    project has found and fixed more than once elsewhere (the compiler's
    job-resume race, the proxy's SecretBindings race).
    """
    with conn.cursor() as cur:
        cur.execute("UPDATE runs SET next_event_seq = next_event_seq + 1 WHERE id = %s RETURNING next_event_seq - 1", (run_id,))
        row = cur.fetchone()
        if row is None:
            raise ValueError(f"run {run_id} not found")
        seq = row[0]
        cur.execute(
            "INSERT INTO run_events (run_id, seq, kind, payload) VALUES (%s, %s, %s, %s)",
            (run_id, seq, kind, json.dumps(dict(payload))),
        )


_STEP_COLUMNS = "id, run_id, node_version_hash, seq, status, attempt, failure_class, next_attempt_at"


def create_run(conn: psycopg.Connection, run_id: str, workflow_version_id: str) -> None:
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO runs (id, workflow_version_id, status) VALUES (%s, %s, 'running')",
            (run_id, workflow_version_id),
        )
    _append_event(conn, run_id, "run_started", {"workflow_version_id": workflow_version_id})
    conn.commit()


def create_step(conn: psycopg.Connection, step_id: str, run_id: str, node_version_hash: str, seq: int) -> None:
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO run_steps (id, run_id, node_version_hash, seq, status) VALUES (%s, %s, %s, %s, 'pending')",
            (step_id, run_id, node_version_hash, seq),
        )
    _append_event(conn, run_id, "step_created", {"step_id": step_id, "seq": seq})
    conn.commit()


def get_step(conn: psycopg.Connection, step_id: str) -> RunStep:
    # dict_row + RunStep(**row), not a positional tuple unpack: found during
    # the milestone 5a audit that RunStep(*row) silently depends on
    # _STEP_COLUMNS' SELECT order exactly matching RunStep's field
    # declaration order, with nothing to catch a future mismatch (wrong
    # values silently assigned to wrong fields, not an error). Keying by
    # column name makes a future rename/reorder mismatch a loud
    # TypeError (unexpected/missing keyword argument) instead.
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(f"SELECT {_STEP_COLUMNS} FROM run_steps WHERE id = %s", (step_id,))
        row = cur.fetchone()
    if row is None:
        raise ValueError(f"run step {step_id} not found")
    return RunStep(**row)


def record_step_success(conn: psycopg.Connection, step_id: str) -> RunStep:
    """Transition a step to succeeded -- a no-op if it's already terminal.

    Found during the milestone 5a audit, reproduced directly: without the
    `status IN ('pending', 'running')` guard, a late or duplicate success
    report for a step that had already reached a terminal state (e.g.
    `permanent_error` from an unretryable `auth` failure, credential alert
    already fired) silently overwrote it back to `succeeded` -- producing
    a run_events log that reads "step_failed (permanent_error) ->
    step_succeeded", as if the step recovered after a failure SPEC.md
    defines as terminal. At-least-once delivery (SPEC.md section 7) means
    a redelivered report for an already-terminal step must be a safe
    no-op, not a silent state transition -- distinguishing a same-outcome
    redelivery from a genuinely contradictory one (already succeeded, now
    reporting failure) is deferred to milestone 5c, which owns duplicate-
    delivery semantics; this guard only prevents corrupting a terminal
    state, deliberately not richer than that.
    """
    with conn.cursor() as cur:
        cur.execute("SELECT run_id FROM run_steps WHERE id = %s FOR UPDATE", (step_id,))
        row = cur.fetchone()
        if row is None:
            raise ValueError(f"run step {step_id} not found")
        run_id = row[0]
        cur.execute(
            "UPDATE run_steps SET status = 'succeeded', ended_at = now() "
            "WHERE id = %s AND status IN ('pending', 'running')",
            (step_id,),
        )
        transitioned = cur.rowcount == 1
    if not transitioned:
        conn.rollback()  # nothing changed; release the row lock cleanly
        return get_step(conn, step_id)
    _append_event(conn, run_id, "step_succeeded", {"step_id": step_id})
    conn.commit()
    return get_step(conn, step_id)


_TERMINAL_STATUSES = frozenset({"succeeded", "permanent_error", "retryable_error"})


def record_step_failure(
    conn: psycopg.Connection,
    step_id: str,
    failure_class: FailureClass,
    retry_after_seconds: float | None = None,
) -> RunStep:
    """Classify a step's failure and persist the resulting state atomically.

    `SELECT ... FOR UPDATE` locks the step row for the duration of this
    transaction, so two concurrent failure reports for the same step_id
    can't both read the same `attempt` and race to write conflicting
    outcomes -- the second one blocks until the first commits, then sees
    the updated attempt count.

    A step already in a terminal status is left unchanged (same rationale
    as record_step_success's guard, added during the milestone 5a audit):
    a late or duplicate failure report for an already-succeeded or
    already-permanently-failed step must not re-classify or re-journal it.
    """
    with conn.cursor() as cur:
        cur.execute("SELECT run_id, attempt, status FROM run_steps WHERE id = %s FOR UPDATE", (step_id,))
        row = cur.fetchone()
        if row is None:
            raise ValueError(f"run step {step_id} not found")
        run_id, attempt, status = row
        if status in _TERMINAL_STATUSES:
            conn.rollback()
            return get_step(conn, step_id)
        decision = classify_and_route(failure_class, attempt, retry_after_seconds)
        if decision.should_retry:
            next_attempt_at = datetime.now(timezone.utc) + timedelta(seconds=decision.delay_seconds or 0.0)
            cur.execute(
                "UPDATE run_steps SET status = 'pending', attempt = attempt + 1, "
                "failure_class = %s, next_attempt_at = %s WHERE id = %s",
                (failure_class, next_attempt_at, step_id),
            )
        else:
            cur.execute(
                "UPDATE run_steps SET status = %s, failure_class = %s, next_attempt_at = NULL, ended_at = now() "
                "WHERE id = %s",
                (decision.route, failure_class, step_id),
            )
    _append_event(
        conn,
        run_id,
        "step_failed",
        {
            "step_id": step_id,
            "failure_class": failure_class,
            "attempt": attempt,
            "retried": decision.should_retry,
            "route": decision.route,
            "signal": decision.signal,
            "delay_seconds": decision.delay_seconds,
        },
    )
    conn.commit()
    return get_step(conn, step_id)


def list_events(conn: psycopg.Connection, run_id: str) -> list[tuple[int, str, dict[str, object]]]:
    with conn.cursor() as cur:
        cur.execute("SELECT seq, kind, payload FROM run_events WHERE run_id = %s ORDER BY seq", (run_id,))
        return [(seq, kind, payload) for seq, kind, payload in cur.fetchall()]
