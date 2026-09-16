import json
from collections.abc import Mapping

Manifest = Mapping[str, object] | bytes | str
Change = dict[str, object]
_MISSING = object()


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
            result[path] = field_schema.get("type")
    return result


def _required_addition(port_schema: object, field: str) -> bool:
    schema = _object(port_schema)
    required = schema.get("required")
    if not isinstance(required, list):
        return True
    return field.split(".", 1)[0] in required


def _schema_changes(old: dict[str, object], new: dict[str, object]) -> tuple[list[Change], str | None]:
    old_ports = _object(_object(old.get("output_schema")).get("ports"))
    new_ports = _object(_object(new.get("output_schema")).get("ports"))
    changes: list[Change] = []
    reason: str | None = None
    for port in sorted(old_ports.keys() | new_ports.keys()):
        old_fields = _field_types(old_ports.get(port))
        new_fields = _field_types(new_ports.get(port))
        for field in sorted(old_fields.keys() | new_fields.keys()):
            if field not in old_fields:
                changes.append({"port": port, "field": field, "change": "added", "type": new_fields[field]})
                if port in old_ports and _required_addition(new_ports[port], field) and reason is None:
                    reason = f"output port '{port}' gained a required field"
            elif field not in new_fields:
                changes.append({"port": port, "field": field, "change": "removed", "type": old_fields[field]})
                if reason is None:
                    reason = f"output port '{port}' lost field '{field}'"
            elif old_fields[field] != new_fields[field]:
                changes.append(
                    {"port": port, "field": field, "change": "type_changed", "from": old_fields[field], "to": new_fields[field]}
                )
                if reason is None:
                    reason = f"output port '{port}' field '{field}' changed type"
    return changes, reason


def _leaf_changes(old: object, new: object, prefix: str = "") -> list[tuple[str, object, object]]:
    if isinstance(old, dict) and isinstance(new, dict):
        changes: list[tuple[str, object, object]] = []
        for key in sorted(old.keys() | new.keys()):
            path = f"{prefix}.{key}" if prefix else key
            changes.extend(_leaf_changes(old.get(key, _MISSING), new.get(key, _MISSING), path))
        return changes
    if old == new:
        return []
    return [(prefix, None if old is _MISSING else old, None if new is _MISSING else new)]


def _plan_changes(old: dict[str, object], new: dict[str, object]) -> list[Change]:
    def steps(manifest: dict[str, object]) -> dict[str, dict[str, object]]:
        values = _object(manifest.get("plan")).get("steps")
        if not isinstance(values, list):
            return {}
        return {
            step["id"]: step
            for step in values
            if isinstance(step, dict) and isinstance(step.get("id"), str)
        }

    old_steps, new_steps = steps(old), steps(new)
    result: list[Change] = []
    for step_id in sorted(old_steps.keys() | new_steps.keys()):
        old_step = {key: value for key, value in old_steps.get(step_id, {}).items() if key != "id"}
        new_step = {key: value for key, value in new_steps.get(step_id, {}).items() if key != "id"}
        for field, before, after in _leaf_changes(old_step, new_step):
            result.append({"step": step_id, "field": field, "from": before, "to": after})
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
