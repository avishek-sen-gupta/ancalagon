# What a bus that queues nothing hands back, so absence needs no sentinel number.
import pydantic


class NoAgentRef(pydantic.BaseModel, frozen=True): ...
