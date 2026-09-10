# What a budget's field holds: a fixed amount, or no limit at all.
import typing

import pydantic

from ancalagon.contracts.finite import Finite
from ancalagon.contracts.infinite import NO_LIMIT, Infinite


def _written(
    given: int | str | Finite | Infinite, handler: pydantic.ValidatorFunctionWrapHandler
) -> Finite | Infinite:
    if isinstance(given, int):
        return Finite(value=given)
    return Infinite() if given == NO_LIMIT else handler(given)


def _as_read(
    given: int | str | Finite | Infinite,
    handler: pydantic.ValidatorFunctionWrapHandler,
    info: pydantic.ValidationInfo,
) -> Finite | Infinite:
    if info.mode == "json":
        return _written(given, handler)
    return handler(given)


Allowance = typing.Annotated[Finite | Infinite, pydantic.WrapValidator(_as_read)]
