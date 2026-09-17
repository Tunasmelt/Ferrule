import json
import math
from decimal import Decimal


class CanonicalizationError(ValueError):
    """The value cannot be represented in Ferrule's canonical JSON."""


def _reject_constant(token: str) -> None:
    raise CanonicalizationError(f"non-finite number: {token}")


def _reject_duplicate_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise CanonicalizationError(f'duplicate object key: "{key}"')
        result[key] = value
    return result


def _number(value: int | float | Decimal) -> str:
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float) and not math.isfinite(value):
        raise CanonicalizationError("non-finite number")
    decimal = Decimal(str(value))
    if not decimal.is_finite():
        raise CanonicalizationError("non-finite number")
    result = format(decimal, "f")
    if "." in result:
        result = result.rstrip("0").rstrip(".")
    return "0" if decimal.is_zero() else result


def _encode(value: object) -> str:
    if value is None:
        return "null"
    if value is True:
        return "true"
    if value is False:
        return "false"
    if isinstance(value, (int, float, Decimal)):
        return _number(value)
    if isinstance(value, str):
        return json.dumps(value, ensure_ascii=False)
    if isinstance(value, (list, tuple)):
        return "[" + ",".join(_encode(item) for item in value) + "]"
    if isinstance(value, dict):
        if not all(isinstance(key, str) for key in value):
            raise CanonicalizationError("object keys must be strings")
        return "{" + ",".join(
            f"{_encode(key)}:{_encode(value[key])}" for key in sorted(value)
        ) + "}"
    raise CanonicalizationError(f"unsupported value type: {type(value).__name__}")


def canonicalize(value: object | bytes | str) -> bytes:
    """Return the canonical UTF-8 JSON representation of a manifest value."""
    if isinstance(value, (bytes, str)):
        try:
            value = json.loads(
                value,
                parse_float=Decimal,
                parse_int=Decimal,
                parse_constant=_reject_constant,
                object_pairs_hook=_reject_duplicate_keys,
            )
        except (json.JSONDecodeError, UnicodeDecodeError) as error:
            raise CanonicalizationError(str(error)) from error
    try:
        return _encode(value).encode("utf-8")
    except UnicodeEncodeError as error:
        raise CanonicalizationError("strings must contain valid Unicode") from error
