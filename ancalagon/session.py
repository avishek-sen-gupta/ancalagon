# The agent loop: one turn per model call, until an answer, a question, or no turns left.
import collections.abc
import logging
import traceback

import pydantic

from ancalagon.children.children import Children
from ancalagon.children.no_children import NO_CHILDREN
from ancalagon.clock.clock import Clock
from ancalagon.contracts.asked import Asked
from ancalagon.contracts.block import Block
from ancalagon.contracts.completed import Completed
from ancalagon.contracts.delivery import Delivery
from ancalagon.contracts.exhausted import Exhausted
from ancalagon.contracts.failed import Failed
from ancalagon.contracts.idled import Idled
from ancalagon.contracts.idling import Idling
from ancalagon.contracts.message import Message
from ancalagon.contracts.message_role import MessageRole
from ancalagon.contracts.needs_input import NeedsInput
from ancalagon.contracts.outcome import SUMMARY_CHARS, Outcome
from ancalagon.contracts.payload import Payload
from ancalagon.contracts.pending import PENDING, Pending
from ancalagon.contracts.reply import Reply
from ancalagon.contracts.role_of import role_of
from ancalagon.contracts.spend import Spend
from ancalagon.contracts.submitted import Submitted
from ancalagon.contracts.task_spec import TaskSpec
from ancalagon.contracts.text import Text
from ancalagon.contracts.tool_result import ToolResult
from ancalagon.contracts.tool_result_block import ToolResultBlock
from ancalagon.contracts.tool_schema import ToolSchema
from ancalagon.contracts.tool_use_from_model import ToolUseFromModel
from ancalagon.letterbox.letterbox import Letterbox
from ancalagon.letterbox.no_letterbox import NO_LETTERBOX
from ancalagon.llm.llm import LLM
from ancalagon.llm.meter import Meter
from ancalagon.llm.system_prompt import SystemPrompt
from ancalagon.llm.unmetered import UNMETERED
from ancalagon.contracts.tool_category import ToolCategory
from ancalagon.profiles.profile import Profile
from ancalagon.profiles.turn import Turn
from ancalagon.tools.registry.bound_tool import BoundTool
from ancalagon.tools.registry.no_tool import NO_TOOL, NoTool
from ancalagon.tools.registry.registry import Registry
from ancalagon.tools.registry.resolved import resolved
from ancalagon.tools.registry.tool_use import ToolUse
from ancalagon.tools.registry.unknown_tool import UnknownTool
from ancalagon.tools.registry.tool_context import ToolContext
from ancalagon.transcript.demote import for_wire
from ancalagon.transcript.transcript import Transcript

LOGGER = logging.getLogger(__name__)

# A rejected final answer is quoted at length, because it is the evidence for the failure.
REJECTED_CHARS = 2000

NO_ANSWER = "no final answer"


def _answer_summary(answer: pydantic.BaseModel) -> str:
    to_summary = getattr(answer, "to_summary", None)
    if callable(to_summary):
        return str(to_summary())[:SUMMARY_CHARS]
    return answer.model_dump_json()[:SUMMARY_CHARS]


COLLECT_TRIES = 2

NOTE_PREFIX = "Note from the operator: "


def _forcing(tool: BoundTool, forced: BoundTool | NoTool) -> bool:
    return isinstance(forced, BoundTool) and tool.spec == forced.spec


def _answering(forced: BoundTool | NoTool) -> bool:
    return isinstance(forced, BoundTool) and forced.spec.category is ToolCategory.SUBMIT


def _faults(name: str, exc: pydantic.ValidationError) -> str:
    problems = exc.errors(include_input=False)
    listed = "\n".join(
        f"  {'.'.join(str(part) for part in problem['loc'])}: {problem['msg']}"
        for problem in problems
    )
    return f"{name} arguments are invalid:\n{listed}"


class Session:
    def __init__(
        self,
        spec: TaskSpec,
        input: pydantic.BaseModel,
        messages: collections.abc.Sequence[Message],
        transcript: Transcript,
        agent_id: int,
        llm: LLM,
        registry: Registry,
        profile: Profile,
        ctx: ToolContext,
        output_class: type[pydantic.BaseModel],
        clock: Clock,
        children: Children = NO_CHILDREN,
        letterbox: Letterbox = NO_LETTERBOX,
        compact_above_tokens: int = 0,
        keep_recent_messages: int = 8,
        meter: Meter = UNMETERED,
    ):
        self.spec = spec
        self.role = role_of(spec.role)
        self.input = input
        self.messages = list(messages)
        self.transcript = transcript
        self.agent_id = agent_id
        self.llm = llm
        self.registry = registry
        self.profile = profile
        self.ctx = ctx
        self.output_class = output_class
        self.meter = meter
        self.clock = clock
        self.children = children
        self.letterbox = letterbox
        self.compact_above_tokens = compact_above_tokens
        self.keep_recent_messages = keep_recent_messages
        self.remaining = self.role.budget
        self.spent = Spend(turns=0, tool_calls=0)
        self.seq = len(messages)
        if not self.messages:
            self._record(
                MessageRole.USER, [Text(text=f"{spec.goal}\n\nInput: {input.model_dump_json()}")]
            )

    def _wire(self) -> collections.abc.Sequence[Message]:
        return for_wire(self.messages, self.compact_above_tokens, self.keep_recent_messages)

    def _scopes(self) -> str:
        readable = ", ".join(str(r) for r in self.ctx.workspace.read_roots)
        writable = ", ".join(str(r) for r in self.ctx.workspace.write_roots)
        return (
            f"You may read under: {readable}\n"
            f"You may write under: {writable}\n"
            f"Give tools absolute paths. A relative path resolves against the working "
            f"directory, not against these roots, and will usually fail."
        )

    def _system(self, turn: Turn) -> SystemPrompt:
        return SystemPrompt(
            static=f"{self.role.behaviour}\n\n{self.profile.mechanics(turn)}",
            per_item=(
                f"Goal: {self.spec.goal}\n\nInput: {self.input.model_dump_json()}\n\n"
                f"{self._scopes()}"
            ),
        )

    def _complete(
        self,
        turn: Turn,
        tools: collections.abc.Sequence[ToolSchema],
        forced: BoundTool | NoTool,
    ) -> Reply:
        name = forced.spec.declaration.name if isinstance(forced, BoundTool) else ""
        reply = self.llm.complete(self._system(turn), self._wire(), tools, force_tool=name)
        self.meter.record(self.agent_id, reply.usage)
        LOGGER.info(
            "in %s out %s cache created %s read %s",
            reply.usage.prompt_tokens,
            reply.usage.completion_tokens,
            reply.usage.cache_creation_tokens,
            reply.usage.cache_read_tokens,
        )
        return reply

    def _record(self, role: MessageRole, blocks: collections.abc.Sequence[Block]) -> None:
        message = Message(
            role=role,
            blocks=list(blocks),
            agent=self.agent_id,
            seq=self.seq,
            ts=self.clock.now().isoformat(),
        )
        self.seq += 1
        self.messages.append(message)
        self.transcript.write(message)

    def _spent(self) -> Spend:
        return self.spent

    def _text_of(self, reply: Reply) -> str:
        return "".join(b.text for b in reply.blocks if isinstance(b, Text))

    def _run_tools(
        self,
        calls: collections.abc.Sequence[ToolUse | UnknownTool],
        exempt: BoundTool | NoTool,
    ) -> list[tuple[ToolUse, ToolResult]]:
        blocks: list[Block] = []
        results: list[tuple[ToolUse, ToolResult]] = []
        for call in calls:
            if isinstance(call, UnknownTool):
                LOGGER.error("the model called a tool that is not in the registry")
                blocks.append(
                    ToolResultBlock(tool_use_id=call.id, content=call.reason, is_error=True)
                )
                continue
            name = call.tool.spec.declaration.name
            cost = 0 if _forcing(call.tool, exempt) else call.tool.spec.cost
            if not self.remaining.tool_calls.permits(cost):
                blocks.append(
                    ToolResultBlock(
                        tool_use_id=call.id,
                        content=f"tool-call budget exhausted; {name} costs "
                        f"{call.tool.spec.cost} and {self.remaining.tool_calls} remain",
                        is_error=True,
                    )
                )
                continue
            self.remaining = self.remaining.spend_tool_calls(cost)
            self.spent = self.spent.plus_tool_calls(cost)
            try:
                result = call.tool.invoke(call.arguments, self.ctx)
            except pydantic.ValidationError as exc:
                LOGGER.exception("tool %s was called with bad arguments", name)
                result = self.ctx.failure(name, _faults(name, exc))
            results.append((call, result))
            blocks.append(
                ToolResultBlock(
                    tool_use_id=call.id,
                    content=f"{result.summary.text_for_model()}\n[full output: {result.path}]",
                    is_error=not result.ok,
                    path=str(result.path),
                    byte_count=result.byte_count,
                )
            )
        self._record(MessageRole.USER, blocks)
        return results

    def _declarations(self, turn: Turn) -> list[ToolSchema]:
        return [tool.spec.declaration for tool in self.profile.offers(turn)]

    def _prepare_final_turn(self, turn: Turn) -> None:
        said = self.profile.instructs(turn)
        if not said:
            return
        if self.messages and self.messages[-1].role is MessageRole.USER:
            self._record(MessageRole.ASSISTANT, [Text(text="Understood.")])
        self._record(MessageRole.USER, [Text(text=said)])

    def _outcome_of_use(
        self, summary: Payload, final: bool
    ) -> Outcome[pydantic.BaseModel] | Pending:
        if isinstance(summary, Asked):
            return NeedsInput(
                question=summary.question,
                summary=summary.question[:SUMMARY_CHARS],
                spent=self._spent(),
            )
        if isinstance(summary, Idled):
            return Idling(
                summary=summary.text_for_model()[:SUMMARY_CHARS],
                spent=self._spent(),
                seen_through=summary.seen_through,
            )
        if isinstance(summary, Submitted) and final:
            return Exhausted(
                value=summary.answer,
                summary=_answer_summary(summary.answer),
                spent=self._spent(),
            )
        if isinstance(summary, Submitted):
            return Completed(
                value=summary.answer,
                summary=_answer_summary(summary.answer),
                spent=self._spent(),
            )
        return PENDING

    def _settled(
        self, ran: collections.abc.Sequence[tuple[ToolUse, ToolResult]], final: bool
    ) -> Outcome[pydantic.BaseModel] | Pending:
        outcomes = (self._outcome_of_use(result.summary, final) for _, result in ran)
        settled = (outcome for outcome in outcomes if not isinstance(outcome, Pending))
        return next(settled, PENDING)

    def _refused(
        self, ran: collections.abc.Sequence[tuple[ToolUse, ToolResult]]
    ) -> Outcome[pydantic.BaseModel] | Pending:
        rejected = [(call, result) for call, result in ran if not result.ok]
        if not rejected:
            return PENDING
        call, result = rejected[0]
        return Failed(
            error=f"{call.tool.spec.declaration.name} refused: {result.error}",
            summary=call.arguments[:REJECTED_CHARS],
            spent=self._spent(),
        )

    def _uncalled(self, reply: Reply, turn: Turn) -> Outcome[pydantic.BaseModel] | Pending:
        if turn.final:
            return Failed(
                error=NO_ANSWER,
                summary=self._text_of(reply)[:REJECTED_CHARS],
                spent=self._spent(),
            )
        LOGGER.info("the reply called no tool, asking again")
        self._record(MessageRole.USER, [Text(text=self.profile.nudges(turn))])
        return PENDING

    def _evaluate_turn(
        self, reply: Reply, turn: Turn, forced: BoundTool | NoTool
    ) -> Outcome[pydantic.BaseModel] | Pending:
        asked = [b for b in reply.blocks if isinstance(b, ToolUseFromModel)]
        if not asked:
            return self._uncalled(reply, turn)
        ran = self._run_tools(resolved(asked, self.registry), forced)
        from_uses = self._settled(ran, turn.final)
        if not isinstance(from_uses, Pending):
            return from_uses
        if turn.final and _answering(forced):
            return self._ended(ran, asked)
        return PENDING

    def _ended(
        self,
        ran: collections.abc.Sequence[tuple[ToolUse, ToolResult]],
        asked: collections.abc.Sequence[ToolUseFromModel],
    ) -> Outcome[pydantic.BaseModel]:
        match self._refused(ran):
            case Pending():
                return Failed(
                    error=NO_ANSWER,
                    summary=asked[0].arguments[:REJECTED_CHARS],
                    spent=self._spent(),
                )
            case failure:
                return failure

    def _deliver(self) -> Delivery:
        notes = self.letterbox.unread()
        for note in notes:
            self._record(MessageRole.USER, [Text(text=f"{NOTE_PREFIX}{note}")])
        self.letterbox.mark(len(notes))
        return Delivery.NOTE if notes else Delivery.NOTHING

    def run(self) -> Outcome[pydantic.BaseModel]:
        try:
            return self._loop()
        except Exception as exc:
            LOGGER.exception("the session failed")
            return Failed(
                error=traceback.format_exc(),
                summary=str(exc)[: self.ctx.summary_chars],
                spent=self._spent(),
            )

    def _turn(self, delivered: Delivery, tries: int) -> Turn:
        return Turn(
            output_class=self.output_class,
            offered=self.registry.bound(),
            remaining=self.remaining,
            spent=self.spent,
            outstanding=self.children.outstanding(),
            uncollected=self.children.uncollected(),
            tries=tries,
            delivered=delivered,
        )

    def _loop(self) -> Outcome[pydantic.BaseModel]:
        tries = COLLECT_TRIES
        while True:
            turn = self._turn(self._deliver(), tries)
            halted = self.profile.halts(turn)
            if not isinstance(halted, Pending):
                return halted
            forced = self.profile.forces(turn) if turn.final else NO_TOOL
            declarations = self._declarations(turn)
            if turn.final:
                self._prepare_final_turn(turn)
            else:
                self.remaining = self.remaining.spend_turn()
                self.spent = self.spent.plus_turn()
            reply = self._complete(turn, declarations, forced)
            self._record(MessageRole.ASSISTANT, reply.blocks)
            outcome = self._evaluate_turn(reply, turn, forced)
            if not isinstance(outcome, Pending):
                return outcome
            if isinstance(forced, BoundTool) and not _answering(forced):
                tries = (
                    COLLECT_TRIES if self.children.uncollected() != turn.uncollected else tries - 1
                )
