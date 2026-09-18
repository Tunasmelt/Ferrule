"""Deterministic text matching for OpenAPI operation selection."""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum

from .openapi import Operation

MIN_RELEVANCE = 0.2
AMBIGUITY_RATIO = 0.9


class ResolutionStatus(StrEnum):
    RESOLVED = "resolved"
    AMBIGUOUS = "ambiguous"
    NO_MATCH = "no_match"


@dataclass(frozen=True, slots=True)
class ResolutionResult:
    status: ResolutionStatus
    operation: Operation | None = None
    candidates: tuple[Operation, ...] = ()


def _tokens(text: str) -> set[str]:
    # Insert camel-case boundaries before stripping punctuation/path separators.
    expanded = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", text)
    return {token.lower() for token in re.findall(r"[A-Za-z0-9]+", expanded)}


def _score(task_words: set[str], operation: Operation) -> float:
    operation_words = _tokens(" ".join((
        operation.summary,
        operation.description,
        operation.operation_id,
        " ".join(operation.tags),
        operation.path,
    )))
    union = task_words | operation_words
    return len(task_words & operation_words) / len(union) if union else 0.0


def resolve_operation(task: str, operations: list[Operation] | tuple[Operation, ...]) -> ResolutionResult:
    """Rank by Jaccard word-set similarity and refuse weak or near-tied guesses."""
    task_words = _tokens(task)
    ranked = sorted(((_score(task_words, item), item) for item in operations), key=lambda pair: pair[0], reverse=True)
    if not ranked or ranked[0][0] < MIN_RELEVANCE:
        return ResolutionResult(ResolutionStatus.NO_MATCH)
    top_score = ranked[0][0]
    candidates = [item for score, item in ranked if score >= MIN_RELEVANCE and score >= top_score * AMBIGUITY_RATIO]
    if len(candidates) > 1:
        return ResolutionResult(ResolutionStatus.AMBIGUOUS, candidates=tuple(candidates))
    return ResolutionResult(ResolutionStatus.RESOLVED, operation=ranked[0][1])
