# A tool with its argument type erased, so a registry can hold tools of differing shapes.
import collections.abc
import dataclasses

from ancalagon.contracts.tool_result import ToolResult
from ancalagon.contracts.tool_spec import ToolSpec
from ancalagon.tools.registry.tool_context import ToolContext


@dataclasses.dataclass(frozen=True)
class BoundTool:
    spec: ToolSpec
    invoke: collections.abc.Callable[[str, ToolContext], ToolResult]
