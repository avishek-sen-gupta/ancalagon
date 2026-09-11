# Which agent a bus queued, as a value rather than a bare number.
import pydantic


class AgentRef(pydantic.BaseModel, frozen=True):
    id: int
