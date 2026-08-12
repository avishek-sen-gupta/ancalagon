# The system message in two halves: the text every item shares, and this item's own.
import pydantic


class SystemPrompt(pydantic.BaseModel, frozen=True):
    static: str
    per_item: str = ""
