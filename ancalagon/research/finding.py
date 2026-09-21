# One thing a researcher read about, and the page it was read on.
import pydantic


class Finding(pydantic.BaseModel, frozen=True):
    subject: str
    behaviour: str
    enforcement: str
    requirements: str
    url: str
    verified: bool
