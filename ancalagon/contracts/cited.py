# An answer contract that can list every citation it rests on, its own and its children's.
import abc

import pydantic

from ancalagon.contracts.evidence import Evidence


class Cited(pydantic.BaseModel, frozen=True):
    @abc.abstractmethod
    def citations(self) -> tuple[Evidence, ...]: ...
