import pydantic


class FreeText(pydantic.BaseModel, frozen=True):
    text: str
