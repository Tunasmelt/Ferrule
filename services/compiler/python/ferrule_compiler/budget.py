"""Compile-time budget instrumentation (milestone 3c).

Reusable so a later milestone's real node-artifact provenance can record
`compile_duration_ms` per attempt, per SPEC.md's node artifact shape --
this milestone's own test criterion (p50 < 3 min across the compiled set)
just needs the same measurement done for real, not assumed.
"""

from __future__ import annotations

import statistics
import time
from collections.abc import Callable
from typing import TypeVar

T = TypeVar("T")


def timed(fn: Callable[[], T]) -> tuple[T, float]:
    """Run `fn`, returning its result and the elapsed wall-clock seconds."""
    start = time.perf_counter()
    value = fn()
    return value, time.perf_counter() - start


def median_seconds(durations: list[float]) -> float:
    return statistics.median(durations) if durations else 0.0
