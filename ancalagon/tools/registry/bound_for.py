# Binds a tool with whatever hooks its role declared for it, resolved against its own arguments.
from ancalagon.contracts.role import Role
from ancalagon.tools.registry.after import After
from ancalagon.tools.registry.before import Before
from ancalagon.tools.registry.bind_tool import bind_tool
from ancalagon.tools.registry.bound_tool import BoundTool
from ancalagon.tools.registry.resolve_after import resolve_after
from ancalagon.tools.registry.resolve_before import resolve_before
from ancalagon.tools.registry.tool import ArgsT, Tool
from ancalagon.tools.registry.unchecked_after import unchecked_after
from ancalagon.tools.registry.unchecked_before import unchecked_before


def _before(tool: Tool[ArgsT], role: Role) -> Before:
    if tool.name not in role.before:
        return unchecked_before
    return resolve_before(role.before[tool.name], tool.args_model)


def _after(tool: Tool[ArgsT], role: Role) -> After:
    if tool.name not in role.after:
        return unchecked_after
    return resolve_after(role.after[tool.name], tool.args_model)


def bound_for(tool: Tool[ArgsT], role: Role) -> BoundTool:
    return bind_tool(tool, _before(tool, role), _after(tool, role))
