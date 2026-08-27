# Whether one annotation on a function names a model class, and what to say when it does not.
import collections.abc
import typing

import pydantic

Declared = tuple[type[pydantic.BaseModel] | None, str]


def declared(hints: collections.abc.Mapping[str, object], key: str, label: str) -> Declared:
    if key not in hints:
        return None, f"does not annotate {label}"
    found = hints[key]
    if not isinstance(found, type) or not issubclass(found, pydantic.BaseModel):
        return None, f"annotates {key} as {found}, which is not a model class"
    return found, ""


def annotation_fault(
    found: collections.abc.Callable[..., object], key: str, label: str
) -> Declared:
    try:
        return declared(typing.get_type_hints(found), key, label)
    except NameError as exc:
        return None, f"has an annotation that cannot be resolved: {exc}"
