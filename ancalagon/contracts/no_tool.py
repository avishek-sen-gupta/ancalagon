# The answer to "which tool" when there is not one.
import dataclasses


@dataclasses.dataclass(frozen=True)
class NoTool:
    pass


NO_TOOL = NoTool()
