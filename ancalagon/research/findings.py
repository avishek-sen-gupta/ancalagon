# What one researcher found in its area.
import pydantic

from ancalagon.research.finding import Finding


class Findings(pydantic.BaseModel, frozen=True):
    area: str
    entries: tuple[Finding, ...]
