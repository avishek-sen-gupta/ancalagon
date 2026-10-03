# What the registry says about a call naming a tool it does not hold.
import dataclasses


@dataclasses.dataclass(frozen=True)
class UnknownTool:
    id: str
    reason: str
