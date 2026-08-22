# Arguments for converting a document into something readable.
import pathlib

import pydantic

from ancalagon.tools.artifacts.document_format import DocumentFormat


class ConvertArgs(pydantic.BaseModel, frozen=True):
    path: pathlib.PurePath
    to: DocumentFormat = DocumentFormat.MARKDOWN
