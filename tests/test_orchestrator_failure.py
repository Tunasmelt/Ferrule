import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / "services" / "orchestrator" / "python"))

from ferrule_orchestrator.failure import (  # noqa: E402
    MAX_BACKOFF_SECONDS,
    MAX_RATE_LIMITED_ATTEMPTS,
    MAX_TIMEOUT_ATTEMPTS,
    MAX_TRANSIENT_ATTEMPTS,
    classify_and_route,
)


class FailureClassificationTests(unittest.TestCase):
    """SPEC.md section 7's 6 failure classes, each checked against its own row."""

    def test_transient_retries_with_backoff_and_jitter_then_routes_retryable(self) -> None:
        for attempt in range(1, MAX_TRANSIENT_ATTEMPTS):
            decision = classify_and_route("transient", attempt)
            self.assertTrue(decision.should_retry, f"attempt {attempt} should retry")
            assert decision.delay_seconds is not None
            self.assertGreaterEqual(decision.delay_seconds, 0.0)
            self.assertLessEqual(decision.delay_seconds, MAX_BACKOFF_SECONDS)
        exhausted = classify_and_route("transient", MAX_TRANSIENT_ATTEMPTS)
        self.assertFalse(exhausted.should_retry)
        self.assertEqual("retryable_error", exhausted.route)
        self.assertIsNone(exhausted.signal)

    def test_auth_never_retries_and_routes_permanent_with_credential_alert(self) -> None:
        decision = classify_and_route("auth", 1)
        self.assertFalse(decision.should_retry)
        self.assertEqual("permanent_error", decision.route)
        self.assertEqual("credential_alert", decision.signal)
        self.assertIsNone(decision.delay_seconds)

    def test_schema_mismatch_never_retries_and_routes_permanent_with_drift_signal(self) -> None:
        decision = classify_and_route("schema_mismatch", 1)
        self.assertFalse(decision.should_retry)
        self.assertEqual("permanent_error", decision.route)
        self.assertEqual("drift_signal", decision.signal)

    def test_permission_denied_never_retries_and_routes_permanent_with_security_event(self) -> None:
        decision = classify_and_route("permission_denied", 1)
        self.assertFalse(decision.should_retry)
        self.assertEqual("permanent_error", decision.route)
        self.assertEqual("security_event", decision.signal)

    def test_timeout_retries_exactly_once_then_routes_retryable(self) -> None:
        self.assertEqual(2, MAX_TIMEOUT_ATTEMPTS, "SPEC.md: timeout retries \"once\" == 2 attempts total")
        first = classify_and_route("timeout", 1)
        self.assertTrue(first.should_retry)
        second = classify_and_route("timeout", 2)
        self.assertFalse(second.should_retry)
        self.assertEqual("retryable_error", second.route)

    def test_rate_limited_honours_retry_after_over_computed_backoff(self) -> None:
        decision = classify_and_route("rate_limited", 1, retry_after_seconds=17.5)
        self.assertTrue(decision.should_retry)
        self.assertEqual(17.5, decision.delay_seconds)

    def test_rate_limited_falls_back_to_backoff_without_retry_after(self) -> None:
        decision = classify_and_route("rate_limited", 1, retry_after_seconds=None)
        self.assertTrue(decision.should_retry)
        assert decision.delay_seconds is not None
        self.assertGreaterEqual(decision.delay_seconds, 0.0)

    def test_rate_limited_exhausts_after_max_attempts(self) -> None:
        exhausted = classify_and_route("rate_limited", MAX_RATE_LIMITED_ATTEMPTS, retry_after_seconds=5.0)
        self.assertFalse(exhausted.should_retry)
        self.assertEqual("retryable_error", exhausted.route)

    def test_backoff_grows_with_attempt_number_on_average(self) -> None:
        # Full jitter is random (uniform(0, cap)), so compare average delay
        # across many samples rather than asserting a strict per-call
        # ordering, which jitter would make flaky.
        import statistics

        def _delay(attempt: int) -> float:
            decision = classify_and_route("transient", attempt)
            assert decision.delay_seconds is not None
            return decision.delay_seconds

        samples_early = [_delay(1) for _ in range(200)]
        samples_late = [_delay(MAX_TRANSIENT_ATTEMPTS - 1) for _ in range(200)]
        self.assertLess(statistics.mean(samples_early), statistics.mean(samples_late))


if __name__ == "__main__":
    unittest.main()
