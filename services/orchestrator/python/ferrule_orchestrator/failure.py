"""Failure classification and retry routing, per SPEC.md section 7:

| Class              | Retry                    | Route after exhaustion (+ signal)      |
|---------------------|--------------------------|------------------------------------------|
| transient           | yes, backoff + jitter    | retryable_error                          |
| auth                | no                       | permanent_error + credential_alert       |
| schema_mismatch     | no                       | permanent_error + drift_signal           |
| permission_denied   | no                       | permanent_error + security_event         |
| timeout             | once                     | retryable_error                          |
| rate_limited        | yes, honour Retry-After  | retryable_error                          |

This module is pure and has no Postgres dependency -- classification is a
deterministic function of (failure_class, attempt, retry_after), not
storage. `state_machine.py` is the only thing that persists its decisions.
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Literal

FailureClass = Literal["transient", "auth", "schema_mismatch", "permission_denied", "timeout", "rate_limited"]
Route = Literal["retryable_error", "permanent_error"]

# SPEC.md's table gives "timeout" an exact count ("once" = one retry, two
# attempts total). It does not give "transient"/"rate_limited" an exact
# number -- these are this orchestrator's own bounded defaults, chosen the
# same way MAX_DOCUMENT_BYTES/MIN_RELEVANCE etc. were chosen elsewhere in
# this project: a reasoned, documented default rather than unbounded
# retries, not a literal spec requirement.
MAX_TRANSIENT_ATTEMPTS = 3
MAX_TIMEOUT_ATTEMPTS = 2
MAX_RATE_LIMITED_ATTEMPTS = 5
BASE_BACKOFF_SECONDS = 1.0
MAX_BACKOFF_SECONDS = 30.0

_NO_RETRY_SIGNAL: dict[FailureClass, str] = {
    "auth": "credential_alert",
    "schema_mismatch": "drift_signal",
    "permission_denied": "security_event",
}
_MAX_ATTEMPTS: dict[FailureClass, int] = {
    "transient": MAX_TRANSIENT_ATTEMPTS,
    "timeout": MAX_TIMEOUT_ATTEMPTS,
    "rate_limited": MAX_RATE_LIMITED_ATTEMPTS,
}


@dataclass(frozen=True, slots=True)
class RoutingDecision:
    should_retry: bool
    route: Route | None  # set only when should_retry is False
    signal: str | None  # credential_alert / drift_signal / security_event
    delay_seconds: float | None  # set only when should_retry is True


def _backoff_with_full_jitter(attempt: int) -> float:
    """AWS-style "full jitter": uniform(0, min(max, base * 2**(attempt-1))).

    Chosen over plain exponential backoff specifically because SPEC.md
    requires jitter, not just backoff -- full jitter is the standard
    algorithm for avoiding synchronized retry storms across many callers.
    """
    capped = min(MAX_BACKOFF_SECONDS, BASE_BACKOFF_SECONDS * (2 ** (attempt - 1)))
    return random.uniform(0, capped)


def classify_and_route(
    failure_class: FailureClass, attempt: int, retry_after_seconds: float | None = None
) -> RoutingDecision:
    """Decide whether/how to retry after the `attempt`-th failure of `failure_class`.

    `attempt` is the attempt number that just failed (1-indexed).
    `retry_after_seconds` is only meaningful for rate_limited (an
    upstream Retry-After header) and is always honoured over the computed
    backoff when present, per SPEC.md's "honour Retry-After".
    """
    if failure_class in _NO_RETRY_SIGNAL:
        return RoutingDecision(
            should_retry=False, route="permanent_error", signal=_NO_RETRY_SIGNAL[failure_class], delay_seconds=None
        )

    if attempt >= _MAX_ATTEMPTS[failure_class]:
        return RoutingDecision(should_retry=False, route="retryable_error", signal=None, delay_seconds=None)

    if failure_class == "rate_limited" and retry_after_seconds is not None:
        delay = max(0.0, retry_after_seconds)
    else:
        delay = _backoff_with_full_jitter(attempt)
    return RoutingDecision(should_retry=True, route=None, signal=None, delay_seconds=delay)
