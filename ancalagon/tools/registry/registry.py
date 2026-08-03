# The tools one agent may call, looked up by the name the model uses.
import collections.abc

from ancalagon.llm.tool_schema import ToolSchema
from ancalagon.tools.registry.tool import Tool


class Registry:
    def __init__(self, tools: collections.abc.Sequence[Tool]):
        self.tools = {t.name: t for t in tools}

    def get(self, name: str) -> Tool:
        if name not in self.tools:
            raise KeyError(f"unknown tool {name}")
        return self.tools[name]

    def names(self) -> list[str]:
        return list(self.tools)

    def schemas(self) -> list[ToolSchema]:
        return [t.schema() for t in self.tools.values()]
