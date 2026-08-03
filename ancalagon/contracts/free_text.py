# The default output contract, for agents whose answer is prose.
import pydantic


class FreeText(pydantic.BaseModel, frozen=True):
    text: str
