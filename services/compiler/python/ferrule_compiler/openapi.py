"""Dependency-light OpenAPI 3.x ingest."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass

import yaml  # type: ignore[import-untyped]

HTTP_METHODS = ("get", "post", "put", "patch", "delete")


class OpenAPIIngestError(ValueError):
    """Base class for rejected source documents."""


class InvalidDocumentError(OpenAPIIngestError):
    """The bytes are not a JSON or YAML document."""


class InvalidOpenAPIError(OpenAPIIngestError):
    """The document is serialized correctly but is not supported OpenAPI."""


@dataclass(frozen=True, slots=True)
class Operation:
    operation_id: str
    method: str
    path: str
    summary: str
    description: str
    tags: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class IngestedSpec:
    source_hash: str
    openapi_version: str
    operations: tuple[Operation, ...]


def _load(raw: bytes) -> object:
    """Prefer strict JSON, then accept YAML as API documentation commonly uses both."""
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as error:
        raise InvalidDocumentError("document must be valid UTF-8 JSON or YAML") from error
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        try:
            return yaml.safe_load(text)
        except yaml.YAMLError as error:
            raise InvalidDocumentError("document is not valid JSON or YAML") from error


def _fallback_id(method: str, path: str) -> str:
    parts = re.findall(r"[A-Za-z0-9]+", path)
    normalized = [part.lower() for part in parts]
    return "-".join((method, *normalized[:-1], "by", normalized[-1])) if "{" in path else "-".join((method, *normalized))


def _text(value: object) -> str:
    return value if isinstance(value, str) else ""


def ingest(raw: bytes) -> IngestedSpec:
    document = _load(raw)
    if not isinstance(document, dict):
        raise InvalidOpenAPIError("OpenAPI document must be an object")
    missing = [key for key in ("openapi", "info", "paths") if key not in document]
    if missing:
        raise InvalidOpenAPIError("OpenAPI document is missing required keys: " + ", ".join(missing))
    version = document["openapi"]
    if not isinstance(version, str) or not re.fullmatch(r"3(?:\.\d+){1,2}(?:[-+].*)?", version):
        raise InvalidOpenAPIError("openapi must be a 3.x version string")
    if not isinstance(document["info"], dict):
        raise InvalidOpenAPIError("info must be an object")
    paths = document["paths"]
    if not isinstance(paths, dict):
        raise InvalidOpenAPIError("paths must be an object")

    operations: list[Operation] = []
    seen_ids: dict[str, int] = {}
    for path, path_item in paths.items():
        if not isinstance(path, str) or not isinstance(path_item, dict):
            continue
        for method in HTTP_METHODS:
            operation = path_item.get(method)
            if not isinstance(operation, dict):
                continue
            operation_id = _text(operation.get("operationId")) or _fallback_id(method, path)
            # Word-based fallback ids can collide across structurally different
            # paths (e.g. "/foo/bar" and "/foo-bar" both tokenize to "foo bar").
            # An undetected collision would let a resume's exact-id lookup
            # silently pick the wrong operation, so disambiguate deterministically.
            if operation_id in seen_ids:
                seen_ids[operation_id] += 1
                operation_id = f"{operation_id}-{seen_ids[operation_id]}"
            else:
                seen_ids[operation_id] = 1
            raw_tags = operation.get("tags", [])
            tags = tuple(tag for tag in raw_tags if isinstance(tag, str)) if isinstance(raw_tags, list) else ()
            operations.append(
                Operation(
                    operation_id=operation_id,
                    method=method.upper(),
                    path=path,
                    summary=_text(operation.get("summary")),
                    description=_text(operation.get("description")),
                    tags=tags,
                )
            )
    return IngestedSpec(
        source_hash="sha256:" + hashlib.sha256(raw).hexdigest(),
        openapi_version=version,
        operations=tuple(operations),
    )
