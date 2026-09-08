# A parameter schema with every $ref inlined, so the wire carries the whole shape.
from pydantic.json_schema import GenerateJsonSchema, JsonSchemaMode, JsonSchemaValue
from pydantic_core.core_schema import CoreSchema

DEFS = "$defs"
REF = "$ref"

Element = JsonSchemaValue | str | int | float | bool | None
Elements = list[Element]


def _item(value: Element, defs: JsonSchemaValue, seen: tuple[str, ...]) -> Element:
    if isinstance(value, dict):
        return _inlined(value, defs, seen)
    return value


def _value(
    value: Element | Elements, defs: JsonSchemaValue, seen: tuple[str, ...]
) -> Element | Elements:
    if isinstance(value, list):
        return [_item(item, defs, seen) for item in value]
    return _item(value, defs, seen)


def _resolved(name: str, defs: JsonSchemaValue, seen: tuple[str, ...]) -> JsonSchemaValue:
    if name in seen:
        raise ValueError(f"a recursive schema cannot be inlined: {' -> '.join((*seen, name))}")
    return _inlined(defs[name], defs, (*seen, name))


def _inlined(
    node: JsonSchemaValue, defs: JsonSchemaValue, seen: tuple[str, ...]
) -> JsonSchemaValue:
    if REF in node:
        return _resolved(str(node[REF]).rsplit("/", 1)[-1], defs, seen)
    return {key: _value(value, defs, seen) for key, value in node.items()}


class Inlined(GenerateJsonSchema):
    def generate(self, schema: CoreSchema, mode: JsonSchemaMode = "validation") -> JsonSchemaValue:
        built = super().generate(schema, mode)
        return _inlined(
            {key: value for key, value in built.items() if key != DEFS}, built.get(DEFS, {}), ()
        )
