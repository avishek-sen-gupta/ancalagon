# An answer that lives in a file: what a parent learns without opening it, and where it is.
import pathlib

import pydantic

from ancalagon.contracts.answer_status import AnswerStatus


class AnswerFile(pydantic.BaseModel, frozen=True):
    status: AnswerStatus
    summary: str
    path: pathlib.PurePath
