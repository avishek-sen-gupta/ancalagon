# An outcome read for its kind alone, without resolving the answer class it carries.
import pydantic

from ancalagon.contracts.outcome_kind import OutcomeKind


class OutcomeHeader(pydantic.BaseModel, frozen=True):
    kind: OutcomeKind
