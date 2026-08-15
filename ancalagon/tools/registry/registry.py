# The tools one agent may call, looked up by the name the model uses.
import collections.abc

from ancalagon.llm.tool_schema import ToolSchema
from ancalagon.tools.registry.bound_tool import BoundTool


class Registry:
    def __init__(self, tools: collections.abc.Sequence[BoundTool]):
        self.tools = {t.name: t for t in tools}

    def get(self, name: str) -> BoundTool:
        if name not in self.tools:
            raise KeyError(f"unknown tool {name}")
        return self.tools[name]

    def names(self) -> list[str]:
        return list(self.tools)

    def schemas(self) -> list[ToolSchema]:
        return [t.declaration for t in self.tools.values()]
