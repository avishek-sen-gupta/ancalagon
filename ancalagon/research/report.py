# The survey the research root puts together from its researchers' findings.
import pydantic

from ancalagon.research.claim import Claim
from ancalagon.research.undetermined import Undetermined


class Report(pydantic.BaseModel, frozen=True):
    differences: tuple[Claim, ...]
    claims: tuple[Claim, ...]
    undetermined: tuple[Undetermined, ...]
