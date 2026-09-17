import json
from collections.abc import Mapping

Manifest = Mapping[str, object] | bytes | str
Change = dict[str, object]
_MISSING = object()
# New cross-language change values: became_required, became_optional,
# constraint_changed, and port_removed.
_CONSTRAINTS = (
    "enum",
    "const",
    "pattern",
    "minimum",
    "maximum",
    "exclusiveMinimum",
    "exclusiveMaximum",
    "additionalProperties",
)


def _manifest(value: Manifest) -> dict[str, object]:
    parsed: object = json.loads(value) if isinstance(value, (bytes, str)) else value
    if not isinstance(parsed, dict):
        raise TypeError("manifest must be a JSON object")
    return parsed


def _object(value: object) -> dict[str, object]:
    return value if isinstance(value, dict) else {}


def _field_types(schema: object, prefix: str = "") -> dict[str, object]:
    result: dict[str, object] = {}
    properties = _object(_object(schema).get("properties"))
    for name in sorted(properties):
        field_schema = _object(properties[name])
        path = f"{prefix}.{name}" if prefix else name
        nested = _field_types(field_schema, path)
        if nested:
            result.update(nested)
        else:
            result[path] = field_schema
    return result


def _required_addition(port_schema: object, field: str) -> bool:
    schema = _object(port_schema)
    required = schema.get("required")
    if not isinstance(required, list):
        return True
    return field.split(".", 1)[0] in required


def _required(port_schema: object, field: str) -> bool:
    required = _object(port_schema).get("required")
    return isinstance(required, list) and field.split(".", 1)[0] in required


def _enum_contains(values: object, target: object) -> bool:
    return isinstance(values, list) and any(value == target for value in values)


def _constraint_tightened(name: str, old: object, new: object) -> bool:
    if new is _MISSING:
        return False
    if old is _MISSING:
        return name != "additionalProperties" or new is not True
    if name == "enum" and isinstance(old, list) and isinstance(new, list):
        return any(not _enum_contains(new, value) for value in old)
    if name in ("minimum", "exclusiveMinimum"):
        return (
            isinstance(old, (int, float))
            and isinstance(new, (int, float))
            and new > old
        )
    if name in ("maximum", "exclusiveMaximum"):
        return (
            isinstance(old, (int, float))
            and isinstance(new, (int, float))
            and new < old
        )
    if name == "additionalProperties":
        return old is not False and new is not True
    return old != new


def _schema_changes(
    old: dict[str, object], new: dict[str, object]
) -> tuple[list[Change], str | None]:
    old_ports = _object(_object(old.get("output_schema")).get("ports"))
    new_ports = _object(_object(new.get("output_schema")).get("ports"))
    changes: list[Change] = []
    reason: str | None = None
    for port in sorted(old_ports.keys() | new_ports.keys()):
        if port not in new_ports:
            changes.append({"port": port, "field": "", "change": "port_removed"})
            if reason is None:
                reason = f"output port '{port}' was removed"
            continue
        old_fields = _field_types(old_ports.get(port))
        new_fields = _field_types(new_ports.get(port))
        for field in sorted(old_fields.keys() | new_fields.keys()):
            if field not in old_fields:
                changes.append(
                    {
                        "port": port,
                        "field": field,
                        "change": "added",
                        "type": _object(new_fields[field]).get("type"),
                    }
                )
                if (
                    port in old_ports
                    and _required_addition(new_ports[port], field)
                    and reason is None
                ):
                    reason = f"output port '{port}' gained a required field"
            elif field not in new_fields:
                changes.append(
                    {
                        "port": port,
                        "field": field,
                        "change": "removed",
                        "type": _object(old_fields[field]).get("type"),
                    }
                )
                if reason is None:
                    reason = f"output port '{port}' lost field '{field}'"
            else:
                old_field, new_field = (
                    _object(old_fields[field]),
                    _object(new_fields[field]),
                )
                if old_field.get("type") != new_field.get("type"):
                    changes.append(
                        {
                            "port": port,
                            "field": field,
                            "change": "type_changed",
                            "from": old_field.get("type"),
                            "to": new_field.get("type"),
                        }
                    )
                    if reason is None:
                        reason = f"output port '{port}' field '{field}' changed type"
                old_required, new_required = (
                    _required(old_ports[port], field),
                    _required(new_ports[port], field),
                )
                if old_required != new_required:
                    # Whole-field change values shared with Go: became_required/became_optional.
                    change = "became_required" if new_required else "became_optional"
                    changes.append(
                        {
                            "port": port,
                            "field": field,
                            "change": change,
                            "from": old_required,
                            "to": new_required,
                        }
                    )
                    if new_required and reason is None:
                        reason = f"output port '{port}' field '{field}' became required"
                for constraint in _CONSTRAINTS:
                    before = old_field.get(constraint, _MISSING)
                    after = new_field.get(constraint, _MISSING)
                    if before is _MISSING and after is _MISSING or before == after:
                        continue
                    # Field-constraint changes use constraint_changed in both implementations.
                    changes.append(
                        {
                            "port": port,
                            "field": field,
                            "change": "constraint_changed",
                            "constraint": constraint,
                            "from": None if before is _MISSING else before,
                            "to": None if after is _MISSING else after,
                        }
                    )
                    if (
                        _constraint_tightened(constraint, before, after)
                        and reason is None
                    ):
                        reason = f"output port '{port}' field '{field}' constraint '{constraint}' tightened"
    return changes, reason


def _leaf_changes(
    old: object, new: object, prefix: str = ""
) -> list[tuple[str, object, object]]:
    if isinstance(old, dict) and isinstance(new, dict):
        changes: list[tuple[str, object, object]] = []
        for key in sorted(old.keys() | new.keys()):
            path = f"{prefix}.{key}" if prefix else key
            changes.extend(
                _leaf_changes(old.get(key, _MISSING), new.get(key, _MISSING), path)
            )
        return changes
    if old == new:
        return []
    return [
        (prefix, None if old is _MISSING else old, None if new is _MISSING else new)
    ]


def _plan_changes(old: dict[str, object], new: dict[str, object]) -> list[Change]:
    def steps(
        plan: dict[str, object],
    ) -> tuple[dict[str, dict[str, object]], list[str], dict[str, int]]:
        values = plan.get("steps")
        if not isinstance(values, list):
            return {}, [], {}
        by_id: dict[str, dict[str, object]] = {}
        order: list[str] = []
        counts: dict[str, int] = {}
        for step in values:
            if isinstance(step, dict) and isinstance(step.get("id"), str):
                step_id = step["id"]
                by_id[step_id] = step
                order.append(step_id)
                counts[step_id] = counts.get(step_id, 0) + 1
        return by_id, order, counts

    # A full node manifest nests steps under "plan"; a bare plan document
    # (milestone 1a's shape) has "steps" at its own top level instead, with
    # no "plan" wrapper at all -- fields like "hosts" live there directly.
    # Treat the document itself as the plan sub-object when no "plan" key
    # exists, so "fields other than steps" comparison still finds them.
    old_plan = old["plan"] if isinstance(old.get("plan"), dict) else old
    new_plan = new["plan"] if isinstance(new.get("plan"), dict) else new
    old_plan, new_plan = _object(old_plan), _object(new_plan)
    old_steps, old_order, old_counts = steps(old_plan)
    new_steps, new_order, new_counts = steps(new_plan)
    result = [
        {"field": field, "from": before, "to": after}
        for field, before, after in _leaf_changes(
            {key: value for key, value in old_plan.items() if key != "steps"},
            {key: value for key, value in new_plan.items() if key != "steps"},
        )
    ]
    common = old_steps.keys() & new_steps.keys()
    # Plan-level changes omit "step"; order reports each shared ID once so
    # additions/removals and duplicate-ID findings remain separate changes.
    old_common = list(dict.fromkeys(step for step in old_order if step in common))
    new_common = list(dict.fromkeys(step for step in new_order if step in common))
    if old_common != new_common:
        result.append({"field": "order", "from": old_common, "to": new_common})
    for step_id in sorted(old_counts.keys() | new_counts.keys()):
        old_count, new_count = old_counts.get(step_id, 0), new_counts.get(step_id, 0)
        if old_count > 1 or new_count > 1:
            result.append(
                {
                    "step": step_id,
                    "field": "id",
                    "change": "duplicate",
                    "from": old_count,
                    "to": new_count,
                }
            )
    for step_id in sorted(old_steps.keys() | new_steps.keys()):
        old_step = {
            key: value
            for key, value in old_steps.get(step_id, {}).items()
            if key != "id"
        }
        new_step = {
            key: value
            for key, value in new_steps.get(step_id, {}).items()
            if key != "id"
        }
        for field, before, after in _leaf_changes(old_step, new_step):
            result.append(
                {"step": step_id, "field": field, "from": before, "to": after}
            )
    return result


def diff(old_manifest: Manifest, new_manifest: Manifest) -> dict[str, object]:
    """Return a deterministic, JSON-serializable artifact manifest diff."""
    old, new = _manifest(old_manifest), _manifest(new_manifest)
    schema_changes, breaking_reason = _schema_changes(old, new)
    capability_changes = [
        {"field": field, "from": before, "to": after}
        for field, before, after in _leaf_changes(
            _object(old.get("capabilities")), _object(new.get("capabilities"))
        )
    ]
    return {
        "schema_changes": schema_changes,
        "plan_changes": _plan_changes(old, new),
        "capability_changes": capability_changes,
        "breaking": breaking_reason is not None,
        "breaking_reason": breaking_reason,
    }
