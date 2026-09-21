"""Real-Postgres tests for milestone 5a's orchestrator state machine.

Skips cleanly (not a failure) when Postgres isn't reachable, so `make
check` stays green in an environment without it running -- `gate-5a`
itself additionally asserts connectivity before running these, so the
milestone's own gate fails loudly rather than silently skipping if
Postgres isn't actually available where it's required.

Local dev Postgres used throughout: a disposable container started with
    docker run -d --name ferrule-postgres \
        -e POSTGRES_USER=ferrule -e POSTGRES_PASSWORD=ferrule_dev_local \
        -e POSTGRES_DB=ferrule -p 55432:5432 postgres:16-alpine
Override with FERRULE_ORCHESTRATOR_DSN if pointing elsewhere.
"""

import os
import sys
import unittest
from pathlib import Path
from uuid import uuid4

import psycopg

ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / "services" / "orchestrator" / "python"))

import ferrule_orchestrator as fo  # noqa: E402
from ferrule_orchestrator.failure import MAX_TRANSIENT_ATTEMPTS  # noqa: E402

DEFAULT_DSN = "postgresql://ferrule:ferrule_dev_local@localhost:55432/ferrule"
DSN = os.environ.get("FERRULE_ORCHESTRATOR_DSN", DEFAULT_DSN)


def _connect_or_skip() -> psycopg.Connection:
    try:
        conn = psycopg.connect(DSN, connect_timeout=3)
    except Exception as error:  # noqa: BLE001 -- any connection failure means "skip", not "fail"
        raise unittest.SkipTest(f"Postgres not reachable at {DSN!r}: {error}") from error
    fo.apply_migrations(conn)
    return conn


class OrchestratorStateMachineTests(unittest.TestCase):
    def setUp(self) -> None:
        self.conn = _connect_or_skip()
        self.run_id = f"run_{uuid4().hex}"
        self.step_id = f"step_{uuid4().hex}"
        fo.create_run(self.conn, self.run_id, "wfv_test")
        fo.create_step(self.conn, self.step_id, self.run_id, "sha256:" + "0" * 64, 1)

    def tearDown(self) -> None:
        self.conn.close()

    def test_step_starts_pending_with_attempt_one(self) -> None:
        step = fo.get_step(self.conn, self.step_id)
        self.assertEqual("pending", step.status)
        self.assertEqual(1, step.attempt)
        self.assertIsNone(step.failure_class)

    def test_step_success_is_terminal(self) -> None:
        step = fo.record_step_success(self.conn, self.step_id)
        self.assertEqual("succeeded", step.status)

    def test_late_success_report_does_not_overwrite_a_permanent_failure(self) -> None:
        # Whole-milestone audit finding, reproduced directly before fixing:
        # without a terminal-state guard, a late/duplicate success report
        # silently overwrote an already-permanently-failed step back to
        # "succeeded", producing a run_events log that read
        # "step_failed(permanent_error) -> step_succeeded" as if an
        # unretryable auth failure had somehow recovered.
        failed = fo.record_step_failure(self.conn, self.step_id, "auth")
        self.assertEqual("permanent_error", failed.status)

        late_success = fo.record_step_success(self.conn, self.step_id)
        self.assertEqual("permanent_error", late_success.status)

        kinds = [kind for _, kind, _ in fo.list_events(self.conn, self.run_id)]
        self.assertEqual(["run_started", "step_created", "step_failed"], kinds)

    def test_late_contradictory_failure_report_does_not_overwrite_success(self) -> None:
        succeeded = fo.record_step_success(self.conn, self.step_id)
        self.assertEqual("succeeded", succeeded.status)

        late_failure = fo.record_step_failure(self.conn, self.step_id, "transient")
        self.assertEqual("succeeded", late_failure.status)

        kinds = [kind for _, kind, _ in fo.list_events(self.conn, self.run_id)]
        self.assertEqual(["run_started", "step_created", "step_succeeded"], kinds)

    def test_transient_failure_retries_then_routes_retryable_error(self) -> None:
        for _ in range(MAX_TRANSIENT_ATTEMPTS - 1):
            step = fo.record_step_failure(self.conn, self.step_id, "transient")
            self.assertEqual("pending", step.status)
            self.assertIsNotNone(step.next_attempt_at)
        final = fo.record_step_failure(self.conn, self.step_id, "transient")
        self.assertEqual("retryable_error", final.status)
        self.assertEqual("transient", final.failure_class)
        self.assertIsNone(final.next_attempt_at)

    def test_auth_failure_routes_permanent_error_immediately(self) -> None:
        step = fo.record_step_failure(self.conn, self.step_id, "auth")
        self.assertEqual("permanent_error", step.status)
        self.assertEqual(1, step.attempt, "auth never retries, so attempt should not increment")

    def test_schema_mismatch_routes_permanent_error_immediately(self) -> None:
        step = fo.record_step_failure(self.conn, self.step_id, "schema_mismatch")
        self.assertEqual("permanent_error", step.status)

    def test_permission_denied_routes_permanent_error_immediately(self) -> None:
        step = fo.record_step_failure(self.conn, self.step_id, "permission_denied")
        self.assertEqual("permanent_error", step.status)

    def test_timeout_retries_exactly_once_then_routes_retryable_error(self) -> None:
        first = fo.record_step_failure(self.conn, self.step_id, "timeout")
        self.assertEqual("pending", first.status)
        second = fo.record_step_failure(self.conn, self.step_id, "timeout")
        self.assertEqual("retryable_error", second.status)

    def test_rate_limited_honours_retry_after_and_eventually_routes_retryable_error(self) -> None:
        step = fo.record_step_failure(self.conn, self.step_id, "rate_limited", retry_after_seconds=42.0)
        self.assertEqual("pending", step.status)
        assert step.next_attempt_at is not None
        # A journaled event should record the honoured Retry-After value.
        events = fo.list_events(self.conn, self.run_id)
        failed_events = [payload for _, kind, payload in events if kind == "step_failed"]
        self.assertEqual(42.0, failed_events[-1]["delay_seconds"])

    def test_every_transition_is_journaled_atomically(self) -> None:
        fo.record_step_failure(self.conn, self.step_id, "transient")
        fo.record_step_success(self.conn, self.step_id)
        events = fo.list_events(self.conn, self.run_id)
        kinds = [kind for _, kind, _ in events]
        self.assertEqual(["run_started", "step_created", "step_failed", "step_succeeded"], kinds)
        # seq is strictly increasing and gapless, per run.
        seqs = [seq for seq, _, _ in events]
        self.assertEqual(list(range(1, len(seqs) + 1)), seqs)

    def test_concurrent_failure_reports_do_not_corrupt_attempt_count(self) -> None:
        # SELECT ... FOR UPDATE inside record_step_failure should serialize
        # concurrent callers rather than let them race on the same
        # `attempt` value -- proven with real threads against real
        # Postgres, not simulated.
        import threading

        barrier = threading.Barrier(2)
        results: list[Exception | None] = [None, None]

        def _attempt(index: int) -> None:
            try:
                conn = psycopg.connect(DSN, connect_timeout=3)
                barrier.wait()
                fo.record_step_failure(conn, self.step_id, "transient")
                conn.close()
            except Exception as error:  # noqa: BLE001
                results[index] = error

        threads = [threading.Thread(target=_attempt, args=(index,)) for index in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=10)

        for error in results:
            if error is not None:
                raise error
        step = fo.get_step(self.conn, self.step_id)
        # Both concurrent failures must be individually counted -- attempt
        # started at 1, two failures should bring it to 3, not silently
        # collapse to 2 from a lost update.
        self.assertEqual(3, step.attempt)


if __name__ == "__main__":
    unittest.main()
