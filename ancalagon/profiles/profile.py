# What an agent of this kind may do. The defaults are an agent that works and never answers.
import pydantic

from ancalagon.contracts.outcome import Outcome
from ancalagon.contracts.pending import PENDING, Pending
from ancalagon.contracts.serialisable_role import SerialisableRole
from ancalagon.contracts.tool_spec import ToolSpec
from ancalagon.profiles.catalogue import Catalogue
from ancalagon.profiles.turn import Turn
from ancalagon.tools.registry.bound_tool import BoundTool
from ancalagon.tools.registry.no_tool import NO_TOOL, NoTool


class Profile:
    tools: tuple[ToolSpec, ...] = ()

    def __init__(self, catalogue: Catalogue) -> None:
        return None

    def faults(self, name: str, role: SerialisableRole, /) -> str:
        return ""

    def halts(self, turn: Turn, /) -> Outcome[pydantic.BaseModel] | Pending:
        return PENDING

    def forces(self, turn: Turn, /) -> BoundTool | NoTool:
        return NO_TOOL

    def offers(self, turn: Turn, /) -> tuple[BoundTool, ...]:
        return turn.offered

    def mechanics(self, turn: Turn, /) -> str:
        return ""

    def instructs(self, turn: Turn, /) -> str:
        return ""

    def nudges(self, turn: Turn, /) -> str:
        return ""
