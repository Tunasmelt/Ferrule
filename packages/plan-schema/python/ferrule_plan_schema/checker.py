import json
import re
from dataclasses import dataclass
from importlib.resources import files
from collections.abc import Iterable
from typing import Mapping, cast
from urllib.parse import urlsplit

from jsonschema import Draft202012Validator  # type: ignore[import-untyped]

from .cel import CELCompileError, compile_expression

_TEMPLATE = re.compile(r"{{\s*([^{}]*?)\s*}}")
_REFERENCE = re.compile(
    r"(?:input|secret|response)\.[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*"
)
_TEMPLATE_FIELDS = ("url", "headers", "query", "body")


@dataclass(frozen=True)
class Finding:
    code: str
    message: str
    path: str


def _schema() -> object:
    resource = files("ferrule_plan_schema").joinpath("plan.schema.json")
    return cast(object, json.loads(resource.read_text(encoding="utf-8")))


def validate_schema(plan: object) -> list[str]:
    validator = Draft202012Validator(_schema())
    errors = sorted(validator.iter_errors(plan), key=lambda error: list(error.path))
    return [f"{_path(error.absolute_path)}: {error.message}" for error in errors]


def _path(parts: Iterable[object]) -> str:
    result = "$"
    for part in parts:
        result += f"[{part}]" if isinstance(part, int) else f".{part}"
    return result


def _mapping(value: object) -> Mapping[str, object] | None:
    if not isinstance(value, dict):
        return None
    return cast(Mapping[str, object], value)


def _strings(step: Mapping[str, object]) -> list[tuple[str, str]]:
    values: list[tuple[str, str]] = []
    for field in _TEMPLATE_FIELDS:
        value = step.get(field)
        if isinstance(value, str):
            values.append((field, value))
        else:
            mapping = _mapping(value)
            if mapping is not None:
                values.extend(
                    (f"{field}.{key}", item)
                    for key, item in mapping.items()
                    if isinstance(item, str)
                )
    return values


def _template_findings(value: str, path: str) -> list[Finding]:
    matches = list(_TEMPLATE.finditer(value))
    findings = [
        Finding(
            "UNBOUND_TEMPLATE_VARIABLE",
            f"template reference {match.group(1)!r} is not an input, secret, or response path",
            path,
        )
        for match in matches
        if _REFERENCE.fullmatch(match.group(1)) is None
    ]
    remainder = _TEMPLATE.sub("", value)
    if "{{" in remainder or "}}" in remainder:
        findings.append(
            Finding("UNBOUND_TEMPLATE_VARIABLE", "malformed template marker", path)
        )
    return findings


def check(plan: object) -> list[Finding]:
    findings = [
        Finding("SCHEMA_INVALID", message, message.partition(":")[0])
        for message in validate_schema(plan)
    ]
    document = _mapping(plan)
    if document is None:
        return findings

    hosts_value = document.get("hosts")
    hosts = {
        host.lower()
        for host in hosts_value if isinstance(host, str)
    } if isinstance(hosts_value, list) else set()
    steps = document.get("steps")
    if not isinstance(steps, list):
        return findings

    # The JSON Schema has no uniqueness constraint on step "id" (uniqueItems
    # would require whole-object equality, not just matching ids), so two
    # steps sharing an id passes schema validation. The proxy's step lookup
    # (services/proxy/authorize.go's findStep) resolves an id to the first
    # matching step, making any later occurrence unreachable/ambiguous by
    # construction. Reject it here rather than let it silently pass, the
    # same way 0a rejects duplicate object keys.
    seen_ids: dict[str, int] = {}
    for index, step_value in enumerate(steps):
        step = _mapping(step_value)
        if step is None:
            continue
        step_id = step.get("id")
        if isinstance(step_id, str):
            if step_id in seen_ids:
                findings.append(
                    Finding(
                        "DUPLICATE_STEP_ID",
                        f"step id {step_id!r} also used by steps[{seen_ids[step_id]}]",
                        f"$.steps[{index}].id",
                    )
                )
            else:
                seen_ids[step_id] = index

    for index, step_value in enumerate(steps):
        step = _mapping(step_value)
        if step is None:
            continue
        base = f"$.steps[{index}]"
        for field, value in _strings(step):
            findings.extend(_template_findings(value, f"{base}.{field}"))

        url = step.get("url")
        if isinstance(url, str):
            stripped_url = _TEMPLATE.sub("", url)
            host = urlsplit(stripped_url).hostname
            if host is None or host.lower() not in hosts:
                displayed_host = host if host is not None else "<missing>"
                findings.append(
                    Finding(
                        "UNDECLARED_HOST",
                        f"URL host {displayed_host!r} is not declared in plan hosts",
                        f"{base}.url",
                    )
                )

        if step.get("pagination") in ("cursor", "offset", "link_header") and "max_pages" not in step:
            findings.append(
                Finding(
                    "UNBOUNDED_PAGINATION",
                    "pagination requires max_pages",
                    f"{base}.max_pages",
                )
            )

        condition = step.get("condition")
        if isinstance(condition, str):
            findings.extend(_cel_findings(condition, f"{base}.condition"))

        expect = _mapping(step.get("expect"))
        if expect is not None and "default" not in expect:
            findings.append(
                Finding(
                    "MISSING_DEFAULT_ROUTE",
                    "expect must include a default route",
                    f"{base}.expect",
                )
            )
        if expect is not None:
            for status, route_value in expect.items():
                route = _mapping(route_value)
                if route is None:
                    continue
                when = route.get("when")
                if isinstance(when, str):
                    findings.extend(_cel_findings(when, f"{base}.expect.{status}.when"))
                mapping = _mapping(route.get("map"))
                if mapping is not None:
                    for name, expression in mapping.items():
                        if isinstance(expression, str):
                            findings.extend(
                                _cel_findings(
                                    expression,
                                    f"{base}.expect.{status}.map.{name}",
                                )
                            )
    return findings


def _cel_findings(source: str, path: str) -> list[Finding]:
    try:
        compile_expression(source)
    except CELCompileError as error:
        return [Finding("CEL_COMPILE_ERROR", str(error), path)]
    return []
