# Every tool an agent could be given, found by the class it was built from.
import collections.abc

from ancalagon.contracts.any_tool import AnyTool
from ancalagon.contracts.tool_spec import ToolSpec
from ancalagon.tools.registry.bound_tool import BoundTool


class Catalogue:
    def __init__(self, available: collections.abc.Sequence[BoundTool]):
        self.specs: collections.abc.Mapping[type[AnyTool], ToolSpec] = {
            t.spec.source: t.spec for t in available
        }

    def spec_for(self, *sources: type[AnyTool]) -> ToolSpec:
        found = [self.specs[source] for source in sources if source in self.specs]
        if not found:
            wanted = " or ".join(source.__name__ for source in sources)
            raise LookupError(f"this agent has no {wanted}")
        return found[0]
