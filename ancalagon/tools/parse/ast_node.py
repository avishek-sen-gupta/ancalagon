# One node of a parsed syntax tree, as the parse tool reports it.
import pydantic


class AstNode(pydantic.BaseModel, frozen=True):
    type: str
    start_byte: int
    end_byte: int
    children: list[str]
