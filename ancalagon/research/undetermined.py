# A question a report could not settle, and why.
import pydantic


class Undetermined(pydantic.BaseModel, frozen=True):
    question: str
    reason: str
