# One match of a tree-sitter query, with every node each capture bound.
import pydantic

from ancalagon.tools.parse.capture import Capture


class QueryMatch(pydantic.BaseModel, frozen=True):
    file: str
    pattern: int
    captures: dict[str, list[Capture]]
