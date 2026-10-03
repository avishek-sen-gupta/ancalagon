# Turns the calls a model asked for into the calls that can actually run.
import collections.abc

from ancalagon.contracts.tool_use_from_model import ToolUseFromModel
from ancalagon.tools.registry.registry import Registry
from ancalagon.tools.registry.tool_use import ToolUse
from ancalagon.tools.registry.unknown_tool import UnknownTool


def resolved(
    asked: collections.abc.Sequence[ToolUseFromModel], registry: Registry
) -> list[ToolUse | UnknownTool]:
    held = set(registry.names())
    return [
        (
            ToolUse(id=use.id, tool=registry.get(use.name), arguments=use.arguments)
            if use.name in held
            else UnknownTool(id=use.id, reason=f"unknown tool {use.name}")
        )
        for use in asked
    ]
