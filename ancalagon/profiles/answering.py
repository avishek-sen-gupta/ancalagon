# An agent that answers once and stops: it collects what its children said, then submits.
import typing

import pydantic

from ancalagon.contracts.any_tool import AnyTool
from ancalagon.contracts.class_ref import ClassRef
from ancalagon.contracts.delivery import Delivery
from ancalagon.contracts.idling import Idling
from ancalagon.contracts.no_answer_file import NO_ANSWER_FILE
from ancalagon.contracts.no_run import NO_RUN
from ancalagon.contracts.no_tool import NoTool
from ancalagon.contracts.no_watermark import NO_WATERMARK
from ancalagon.contracts.outcome import Outcome
from ancalagon.contracts.pending import PENDING, Pending
from ancalagon.contracts.serialisable_role import SerialisableRole
from ancalagon.contracts.tool_spec import ToolSpec
from ancalagon.llm.inlined import Inlined
from ancalagon.profiles.catalogue import Catalogue
from ancalagon.profiles.profile import Profile
from ancalagon.profiles.turn import Turn
from ancalagon.tools.delegate.collect_task import CollectTask
from ancalagon.tools.idle.idle import Idle
from ancalagon.tools.idle.no_idle import NoIdle
from ancalagon.tools.registry.bound_tool import BoundTool
from ancalagon.tools.submit.submit_answer import SubmitAnswer

ANSWERING = ClassRef(module="ancalagon.profiles.answering", name="Answering")

TURNS_GONE = "turns exhausted while children ran"


def run_ref_fault(name: str, kind: str, role: SerialisableRole) -> str:
    if role.run == NO_RUN:
        return ""
    return (
        f"[roles.{name}] is {kind} but names run {role.run.name} in "
        f"{role.run.module}; a role that runs a function holds no session to answer in"
    )


class Answering(Profile):
    terminal_tool: typing.ClassVar[type[AnyTool]] = SubmitAnswer

    def __init__(self, catalogue: Catalogue) -> None:
        super().__init__(catalogue)
        self.terminal = catalogue.spec_for(self.terminal_tool)
        self.collect = catalogue.spec_for(CollectTask)
        self.idle = catalogue.spec_for(Idle, NoIdle)

    @classmethod
    def supplies(cls) -> tuple[tuple[type[AnyTool], ...], ...]:
        return ((cls.terminal_tool,), (Idle, NoIdle))

    @classmethod
    def faults(cls, name: str, role: SerialisableRole, /) -> str:
        if fault := run_ref_fault(name, cls.__name__, role):
            return fault
        if role.answer_file == NO_ANSWER_FILE:
            return ""
        return (
            f"[roles.{name}] declares answer_file as {role.answer_file.name} in "
            f"{role.answer_file.module}, but {cls.__name__} answers with the value "
            "itself, so nothing checks it"
        )

    def halts(self, turn: Turn, /) -> Outcome[pydantic.BaseModel] | Pending:
        if turn.final and turn.outstanding:
            return Idling(summary=TURNS_GONE, spent=turn.spent, seen_through=NO_WATERMARK)
        return PENDING

    def forces(self, turn: Turn, /) -> BoundTool | NoTool:
        if self._collecting(turn):
            return turn.bound(self.collect)
        return turn.bound(self.terminal)

    def offers(self, turn: Turn, /) -> tuple[BoundTool, ...]:
        if turn.final:
            return self._forced_alone(turn)
        withheld = self._withheld(turn)
        return tuple(tool for tool in turn.offered if tool.spec not in withheld)

    def mechanics(self, turn: Turn, /) -> str:
        schema = turn.output_class.model_json_schema(schema_generator=Inlined)
        return (
            f"When you have the answer, call the {self._name()} tool with it. That tool is "
            f"the only way to answer; a reply without it is taken as more work to do. "
            f"Your answer must match this schema: {schema}"
        )

    def instructs(self, turn: Turn, /) -> str:
        if self._collecting(turn):
            return (
                f"Your budget is exhausted, and these children have answers you have never "
                f"read: {list(turn.uncollected)}. Call {self.collect.declaration.name} for one "
                f"of them now. You will be asked for your answer once every one of them has "
                f"been collected."
            )
        return (
            f"Your budget is exhausted. Answer now from what you already know, "
            f"using the {self._name()} tool. No other tools are available."
        )

    def nudges(self, turn: Turn, /) -> str:
        if turn.delivered is Delivery.NOTE:
            return f"Noted. Carry on, and call the {self._name()} tool when you have your answer."
        return (
            f"Answers are only accepted through the {self._name()} tool. Keep working, and "
            f"call it when you have your answer."
        )

    def _name(self) -> str:
        return self.terminal.declaration.name

    def _collecting(self, turn: Turn) -> bool:
        if not (turn.uncollected and turn.tries > 0):
            return False
        return not isinstance(turn.bound(self.collect), NoTool)

    def _forced_alone(self, turn: Turn) -> tuple[BoundTool, ...]:
        forced = self.forces(turn)
        return () if isinstance(forced, NoTool) else (forced,)

    def _withheld(self, turn: Turn) -> frozenset[ToolSpec]:
        idle = frozenset[ToolSpec]() if turn.outstanding else frozenset({self.idle})
        answering = turn.outstanding or turn.uncollected
        return idle | (frozenset({self.terminal}) if answering else frozenset[ToolSpec]())
