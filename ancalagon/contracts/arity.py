# Whether a callable takes exactly the positional parameters a caller will pass it.
import collections.abc
import inspect

POSITIONAL = inspect.Parameter.POSITIONAL_OR_KEYWORD


def arity_fault(found: collections.abc.Callable[..., object], arity: int) -> str:
    params = list(inspect.signature(found).parameters.values())
    if len(params) != arity or any(p.kind is not POSITIONAL for p in params):
        return f"must take {arity} positional parameters, not {[p.name for p in params]}"
    return ""
