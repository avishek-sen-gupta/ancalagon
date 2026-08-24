# Binds a tool with the hooks its role declared for it, resolved against its own arguments.
from ancalagon.contracts.role import Role
from ancalagon.tools.registry.bind_tool import bind_tool
from ancalagon.tools.registry.bound_tool import BoundTool
from ancalagon.tools.registry.composite_after import CompositeAfter
from ancalagon.tools.registry.composite_before import CompositeBefore
from ancalagon.tools.registry.resolve_after import resolve_after
from ancalagon.tools.registry.resolve_before import resolve_before
from ancalagon.tools.registry.tool import ArgsT, Tool


def bound_for(tool: Tool[ArgsT], role: Role) -> BoundTool:
    return bind_tool(
        tool,
        CompositeBefore(
            tuple(resolve_before(ref, tool.args_model) for ref in role.before.get(tool.name, ()))
        ),
        CompositeAfter(
            tuple(resolve_after(ref, tool.args_model) for ref in role.after.get(tool.name, ()))
        ),
    )
