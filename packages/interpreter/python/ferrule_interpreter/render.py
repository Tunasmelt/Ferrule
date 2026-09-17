import re
from collections.abc import Mapping

_MARKER = re.compile(r"{{\s*((?:input|response|secret)(?:\.[A-Za-z_][A-Za-z0-9_]*)+)\s*}}")


def _lookup(path: str, input_value: Mapping[str, object], response: Mapping[str, object]) -> object:
    namespace, *parts = path.split(".")
    if namespace == "secret":
        return "{{ " + path + " }}"
    value: object = input_value if namespace == "input" else response
    for part in parts:
        if not isinstance(value, Mapping) or part not in value:
            return ""
        value = value[part]
    return value


def render(value: str, input_value: Mapping[str, object], response: Mapping[str, object]) -> str:
    def replace(match: re.Match[str]) -> str:
        found = _lookup(match.group(1), input_value, response)
        return str(found).lower() if isinstance(found, bool) else str(found)

    return _MARKER.sub(replace, value)
