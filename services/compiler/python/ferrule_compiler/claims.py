"""Assumption surfacing with source spans (milestone 3c, spec_claims per API.md).

Every GET operation this compiler handles carries at least one assumption:
none of the 8 real fixture specs declare a response body content schema
(only a bare "200": {"description": "OK"}), so the generated plan's
success-route mapping (the whole response body, not named fields) is
always an assumption about shape, not a documented fact. Optional
query/header parameters carry a second, parameter-specific claim describing
generate.py's own known "always sent, never omitted" limitation.

Source spans are resolved by locating real anchor text -- the operation's
own method key, then a more specific sub-anchor within it -- in the raw
document bytes, not fabricated offsets. This only supports JSON documents
(all 8 real fixtures + the synthetic one are JSON); a document where the
anchor can't be located (YAML, or reformatted enough that exact key text
doesn't match) falls back to an empty span rather than a wrong one, which
is a known, documented limitation, not a solved general case.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

from .generate import CompileResult
from .openapi import Operation


@dataclass(frozen=True, slots=True)
class Claim:
    path: str
    claim: str
    source_span: tuple[int, int]
    confidence: float


def _matching_brace(text: str, open_pos: int) -> int | None:
    """Return the index of the "}" matching the "{" at open_pos, respecting string literals."""
    depth = 0
    in_string = False
    escape = False
    for index in range(open_pos, len(text)):
        char = text[index]
        if in_string:
            if escape:
                escape = False
            elif char == "\\":
                escape = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return index
    return None


def _method_block_span(raw_text: str, path: str, method: str) -> tuple[int, int] | None:
    """Locate one path+method's operation object span in raw JSON text, or None if unresolvable."""
    path_pos = raw_text.find(json.dumps(path))
    if path_pos == -1:
        return None
    method_pos = raw_text.find(json.dumps(method.lower()), path_pos)
    if method_pos == -1:
        return None
    colon_pos = raw_text.find(":", method_pos)
    brace_start = raw_text.find("{", colon_pos) if colon_pos != -1 else -1
    if brace_start == -1:
        return None
    brace_end = _matching_brace(raw_text, brace_start)
    if brace_end is None:
        return None
    return (brace_start, brace_end + 1)


def extract_claims(raw: bytes, operation: Operation, result: CompileResult) -> tuple[Claim, ...]:
    """Surface the assumptions made compiling `operation` into `result`.

    Returns an empty tuple only when the operation itself didn't compile
    (nothing was assumed because nothing was generated) or the document
    can't be decoded as UTF-8 text.
    """
    if result.plan is None:
        return ()
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        return ()

    block = _method_block_span(text, operation.path, operation.method)
    fallback_span = block if block is not None else (0, 0)
    base_path = f"/paths/{operation.path}/{operation.method.lower()}"

    claims: list[Claim] = [
        Claim(
            path=f"{base_path}/responses",
            claim=(
                "Success response body shape is not documented (no response "
                "content schema); the whole response body is mapped to the "
                "'ok' route's 'body' output field rather than named fields."
            ),
            source_span=fallback_span,
            confidence=0.5,
        )
    ]

    for limitation in result.limitations:
        span = fallback_span
        if block is not None:
            for parameter in operation.parameters:
                if f"'{parameter.name}'" in limitation:
                    anchor = json.dumps(parameter.name)
                    found = text.find(anchor, block[0], block[1])
                    if found != -1:
                        span = (found, found + len(anchor))
                    break
        claims.append(
            Claim(
                path=f"{base_path}/parameters",
                claim=limitation,
                source_span=span,
                # Not a guess about the target API -- a known fact about
                # this compiler's own generated plan, hence full confidence.
                confidence=1.0,
            )
        )
    return tuple(claims)
