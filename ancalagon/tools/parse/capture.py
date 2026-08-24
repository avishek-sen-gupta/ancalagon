# One named capture of a tree-sitter query match: where it is, and what it says.
import pydantic


class Capture(pydantic.BaseModel, frozen=True):
    type: str
    start_byte: int
    end_byte: int
    start_point: tuple[int, int]
    end_point: tuple[int, int]
    text: str
