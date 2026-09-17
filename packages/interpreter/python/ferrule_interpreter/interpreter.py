from __future__ import annotations

import http.client
import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import cast
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit, urlunsplit

from ferrule_plan_schema import check, compile_expression, evaluate

from .render import render

# Matches the 1 MiB default runtime limit in SPEC.md section 5 while bounding
# each response independently, including every pagination page.
MAX_RESPONSE_BODY_BYTES = 1_048_576


class PlanRejected(ValueError):
    pass


class ResponseTooLargeError(ValueError):
    pass


class UndeclaredHostError(ValueError):
    pass


@dataclass(frozen=True)
class Response:
    status: int
    headers: dict[str, str]
    body: object


@dataclass(frozen=True)
class Request:
    method: str
    url: str
    headers: dict[str, str]
    body: bytes | None


Transport = Callable[[Request], Response]


def _http(request: Request) -> Response:
    parsed = urlsplit(request.url)
    if parsed.hostname is None:
        raise ValueError("request URL has no hostname")
    connection_type = http.client.HTTPSConnection if parsed.scheme == "https" else http.client.HTTPConnection
    connection = connection_type(parsed.hostname, parsed.port, timeout=10)
    target = urlunsplit(("", "", parsed.path or "/", parsed.query, ""))
    try:
        try:
            connection.request(request.method, target, body=request.body, headers=request.headers)
        except ValueError as exc:
            raise PlanRejected("invalid HTTP request headers or target") from exc
        raw = connection.getresponse()
        data = raw.read(MAX_RESPONSE_BODY_BYTES + 1)
        if len(data) > MAX_RESPONSE_BODY_BYTES:
            raise ResponseTooLargeError(f"response body exceeds {MAX_RESPONSE_BODY_BYTES} bytes")
        headers = {name.lower(): value for name, value in raw.getheaders()}
    finally:
        connection.close()
    try:
        body: object = json.loads(data) if data else {}
    except (UnicodeDecodeError, json.JSONDecodeError):
        body = {"text": data.decode("utf-8", errors="replace")}
    return Response(raw.status, headers, body)


def _context(response: Response) -> dict[str, object]:
    body = dict(response.body) if isinstance(response.body, Mapping) else {"data": response.body}
    body.update({"status": response.status, "headers": response.headers})
    return body


def _request(step: Mapping[str, object], input_value: dict[str, object], previous: dict[str, object], declared_hosts: set[str], url: str | None = None) -> Request:
    if url is not None:
        host = urlsplit(url).hostname
        if host is None or host.lower() not in declared_hosts:
            displayed_host = host if host is not None else "<missing>"
            raise UndeclaredHostError(f"pagination URL host {displayed_host!r} is not declared in plan hosts")
    rendered_headers = {
        str(k): render(str(v), input_value, previous)
        for k, v in cast(Mapping[object, object], step["headers"]).items()
    }
    query = {str(k): render(str(v), input_value, previous) for k, v in cast(Mapping[object, object], step.get("query", {})).items()}
    rendered_url = url or render(cast(str, step["url"]), input_value, previous)
    parsed = urlsplit(rendered_url)
    merged = dict(parse_qsl(parsed.query, keep_blank_values=True))
    if url is None:
        merged.update(query)
    rendered_url = urlunsplit((parsed.scheme, parsed.netloc, parsed.path, urlencode(sorted(merged.items())), ""))
    body_value = step.get("body")
    body = None
    if isinstance(body_value, Mapping):
        body = json.dumps({str(k): render(str(v), input_value, previous) for k, v in body_value.items()}, sort_keys=True, separators=(",", ":")).encode()
        rendered_headers.setdefault("Content-Type", "application/json")
    # Title-case each segment and sort names for deterministic HTTP rendering.
    headers = dict(sorted(
        (("-".join(part.capitalize() for part in name.split("-")), value) for name, value in rendered_headers.items()),
    ))
    return Request(cast(str, step["method"]), rendered_url, headers, body)


def _route(step: Mapping[str, object], response: Response, input_value: dict[str, object]) -> tuple[str, dict[str, object]]:
    expect = cast(Mapping[str, object], step["expect"])
    key = str(response.status)
    route_value = expect.get(key, expect.get(f"{response.status // 100}xx", expect["default"]))
    route = cast(Mapping[str, object], route_value)
    context = _context(response)
    when = route.get("when")
    if isinstance(when, str) and not bool(evaluate(compile_expression(when), input_value, context)):
        route = cast(Mapping[str, object], expect["default"])
    mapping = cast(Mapping[str, str], route["map"])
    output = {name: evaluate(compile_expression(expression), input_value, context) for name, expression in mapping.items()}
    return cast(str, route["route"]), output


def _merge(target: dict[str, object], page: dict[str, object]) -> None:
    for key, value in page.items():
        if key in target and isinstance(target[key], list) and isinstance(value, list):
            cast(list[object], target[key]).extend(value)
        else:
            target[key] = value


def _next(step: Mapping[str, object], request: Request, response: Response) -> str | None:
    mode = step["pagination"]
    context = _context(response)
    if mode == "link_header":
        for part in response.headers.get("link", "").split(","):
            if 'rel="next"' in part:
                return urljoin(request.url, part[part.find("<") + 1:part.find(">")])
    if mode == "offset" and isinstance(context.get("next"), str):
        return cast(str, context["next"])
    if mode == "cursor" and context.get("has_more") is True:
        data = context.get("data")
        if isinstance(data, list) and data and isinstance(data[-1], Mapping) and "id" in data[-1]:
            parsed = urlsplit(request.url)
            query = dict(parse_qsl(parsed.query, keep_blank_values=True))
            query["starting_after"] = str(data[-1]["id"])
            return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, urlencode(query), ""))
    return None


def run(plan: object, input: dict[str, object], transport: Transport | None = None) -> dict[str, object]:
    """Execute steps and concatenate list mappings across pages.

    Scalar mappings use the last page. The result is the final step's route
    and mapped output.
    """
    findings = check(plan)
    if findings:
        raise PlanRejected("; ".join(f"{item.code} at {item.path}" for item in findings))
    document = cast(Mapping[str, object], plan)
    declared_hosts = {cast(str, host).lower() for host in cast(list[object], document["hosts"])}
    previous: dict[str, object] = {}
    final: dict[str, object] = {}
    sender = transport or _http
    for step_value in cast(list[object], document["steps"]):
        step = cast(Mapping[str, object], step_value)
        condition = step.get("condition")
        if isinstance(condition, str) and not bool(evaluate(compile_expression(condition), input, previous)):
            continue
        merged: dict[str, object] = {}
        next_url: str | None = None
        route_name = ""
        limit = cast(int, step.get("max_pages", 1))
        for _ in range(limit):
            request = _request(step, input, previous, declared_hosts, next_url)
            response = sender(request)
            route_name, page = _route(step, response, input)
            _merge(merged, page)
            next_url = _next(step, request, response)
            if next_url is None or route_name not in ("ok", "results"):
                break
        previous = merged
        final = {"route": route_name, "output": merged}
    return final
