from typing import Literal, TypeAlias

from ferrule_plan_schema import check

Coverage: TypeAlias = Literal["representable", "representable_partial", "not_representable"]


def classify_plan(plan: object, limitations: tuple[str, ...] = ()) -> Coverage:
    if check(plan):
        return "not_representable"
    return "representable_partial" if limitations else "representable"
