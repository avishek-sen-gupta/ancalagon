# The agent loop: one turn per model call, until an answer, a question, or no turns left.
import collections.abc
import logging

import pydantic

from ancalagon.children.children import Children
from ancalagon.children.no_children import NO_CHILDREN
from ancalagon.clock.clock import Clock
from ancalagon.contracts.asked import Asked
from ancalagon.contracts.block import Block
from ancalagon.contracts.budget import Budget
from ancalagon.contracts.completed import Completed
from ancalagon.contracts.exhausted import Exhausted
from ancalagon.contracts.failed import Failed
from ancalagon.contracts.idled import Idled
from ancalagon.contracts.idling import Idling
from ancalagon.contracts.json_payload import json_payload
from ancalagon.contracts.message import Message
from ancalagon.contracts.message_role import MessageRole
from ancalagon.contracts.needs_input import NeedsInput
from ancalagon.contracts.outcome import SUMMARY_CHARS, Outcome
from ancalagon.contracts.payload import Payload
from ancalagon.contracts.pending import PENDING, Pending
from ancalagon.contracts.reply import Reply
from ancalagon.contracts.submitted import Submitted
from ancalagon.contracts.task_spec import TaskSpec
from ancalagon.contracts.text import Text
from ancalagon.contracts.tool_result import ToolResult
from ancalagon.contracts.tool_result_block import ToolResultBlock
from ancalagon.contracts.tool_use import ToolUse
from ancalagon.llm.llm import LLM
from ancalagon.llm.meter import Meter
from ancalagon.llm.system_prompt import SystemPrompt
from ancalagon.llm.tool_schema import ToolSchema
from ancalagon.llm.unmetered import UNMETERED
from ancalagon.tools.registry.registry import Registry
from ancalagon.tools.registry.tool_context import ToolContext
from ancalagon.transcript.demote import for_wire
from ancalagon.transcript.transcript import Transcript

LOGGER = logging.getLogger(__name__)

# A rejected final answer is quoted at length, because it is the evidence for the failure.
REJECTED_CHARS = 2000

FINAL_INSTRUCTION = (
    "Your budget is exhausted. Answer now from what you already know, "
    "using the submit_answer tool. No other tools are available."
)

SUBMIT = "submit_answer"
IDLE = "idle"


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
        ctx: ToolContext,
        output_class: type[pydantic.BaseModel],
        clock: Clock,
        children: Children = NO_CHILDREN,
        compact_above_tokens: int = 0,
        keep_recent_messages: int = 8,
        meter: Meter = UNMETERED,
    ):
        self.spec = spec
        self.input = input
        self.messages = list(messages)
        self.transcript = transcript
        self.agent_id = agent_id
        self.llm = llm
        self.registry = registry
        self.ctx = ctx
        self.output_class = output_class
        self.meter = meter
        self.clock = clock
        self.children = children
        self.compact_above_tokens = compact_above_tokens
        self.keep_recent_messages = keep_recent_messages
        self.remaining = spec.role.budget
        self.seq = len(messages)
        if not self.messages:
            self._record(
                MessageRole.USER, [Text(text=f"{spec.goal}\n\nInput: {input.model_dump_json()}")]
            )

    def _wire(self) -> collections.abc.Sequence[Message]:
        return for_wire(self.messages, self.compact_above_tokens, self.keep_recent_messages)

    def _scopes(self) -> str:
        readable = ", ".join(str(r) for r in self.ctx.workspace.read_roots)
        return (
            f"You may read under: {readable}\n"
            f"You may write under: {self.ctx.workspace.write_root}\n"
            f"Give tools absolute paths. A relative path resolves against the working "
            f"directory, not against these roots, and will usually fail."
        )

    def _system(self) -> SystemPrompt:
        schema = self.output_class.model_json_schema()
        return SystemPrompt(
            static=(
                f"{self.spec.role.behaviour}\n\n"
                f"When you have the answer, call the submit_answer tool with it. "
                f"If that tool is unavailable, reply with a single JSON object and nothing "
                f"else -- no prose, no markdown fences -- matching this schema: {schema}"
            ),
            per_item=(
                f"Goal: {self.spec.goal}\n\nInput: {self.input.model_dump_json()}\n\n"
                f"{self._scopes()}"
            ),
        )

    def _complete(self, tools: collections.abc.Sequence[ToolSchema], force_tool: str = "") -> Reply:
        reply = self.llm.complete(self._system(), self._wire(), tools, force_tool=force_tool)
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
        self.transcript.append(message)

    def _spent(self) -> Budget:
        return Budget(
            turns=self.spec.role.budget.turns - self.remaining.turns,
            tool_calls=self.spec.role.budget.tool_calls - self.remaining.tool_calls,
        )

    def _text_of(self, reply: Reply) -> str:
        return "".join(b.text for b in reply.blocks if isinstance(b, Text))

    def _answer_of(self, reply: Reply) -> str:
        return json_payload(self._text_of(reply))

    def _run_tools(self, uses: collections.abc.Sequence[ToolUse]) -> list[ToolResult]:
        blocks: list[Block] = []
        results: list[ToolResult] = []
        for use in uses:
            try:
                tool = self.registry.get(use.name)
            except KeyError as exc:
                blocks.append(ToolResultBlock(tool_use_id=use.id, content=str(exc), is_error=True))
                continue
            if tool.cost > self.remaining.tool_calls:
                blocks.append(
                    ToolResultBlock(
                        tool_use_id=use.id,
                        content=f"tool-call budget exhausted; {use.name} costs "
                        f"{tool.cost} and {self.remaining.tool_calls} remain",
                        is_error=True,
                    )
                )
                continue
            self.remaining = self.remaining.spend_tool_calls(tool.cost)
            try:
                result = tool.invoke(use.arguments, self.ctx)
            except pydantic.ValidationError as exc:
                LOGGER.info("tool %s was called with bad arguments: %s", use.name, exc)
                result = self.ctx.failure(use.name, f"{type(exc).__name__}: {exc}")
            results.append(result)
            blocks.append(
                ToolResultBlock(
                    tool_use_id=use.id,
                    content=f"{result.summary.text_for_model()}\n[full output: {result.path}]",
                    is_error=not result.ok,
                    path=str(result.path),
                    byte_count=result.byte_count,
                )
            )
        self._record(MessageRole.USER, blocks)
        return results

    def _declarations(
        self, final: bool, outstanding: collections.abc.Sequence[int]
    ) -> list[ToolSchema]:
        if final:
            return [self.registry.get(SUBMIT).declaration]
        uncollected = self.children.uncollected()
        excluded: set[str] = ({IDLE} if not outstanding else set[str]()) | (
            {SUBMIT} if outstanding or uncollected else set[str]()
        )
        return [
            self.registry.get(name).declaration
            for name in self.registry.names()
            if name not in excluded
        ]

    def _prepare_final_turn(self) -> None:
        if self.messages and self.messages[-1].role is MessageRole.USER:
            self._record(MessageRole.ASSISTANT, [Text(text="Understood.")])
        self._record(MessageRole.USER, [Text(text=FINAL_INSTRUCTION)])

    def _outcome_of_use(self, summary: Payload, final: bool) -> Outcome | Pending:
        if isinstance(summary, Asked):
            return NeedsInput(
                question=summary.question,
                summary=summary.question[:SUMMARY_CHARS],
                spent=self._spent(),
            )
        if isinstance(summary, Idled):
            return Idling(summary=summary.text_for_model()[:SUMMARY_CHARS], spent=self._spent())
        if isinstance(summary, Submitted) and final:
            return Exhausted(
                value=summary.answer,
                summary=summary.answer.model_dump_json()[:SUMMARY_CHARS],
                spent=self._spent(),
            )
        if isinstance(summary, Submitted):
            return Completed(
                value=summary.answer,
                summary=summary.answer.model_dump_json()[:SUMMARY_CHARS],
                spent=self._spent(),
            )
        return PENDING

    def _handle_uses(
        self, uses: collections.abc.Sequence[ToolUse], final: bool
    ) -> Outcome | Pending:
        outcomes = (self._outcome_of_use(result.summary, final) for result in self._run_tools(uses))
        settled = (outcome for outcome in outcomes if not isinstance(outcome, Pending))
        return next(settled, PENDING)

    def _finish_from_text(self, reply: Reply, final: bool, offered: str) -> Outcome | Pending:
        text = self._answer_of(reply)
        try:
            value = self.output_class.model_validate_json(text)
        except pydantic.ValidationError as exc:
            if final:
                return Failed(
                    error=f"final answer did not validate: {exc}",
                    summary=offered[:REJECTED_CHARS] or text[:REJECTED_CHARS],
                    spent=self._spent(),
                )
            LOGGER.info("output did not validate, asking again: %s", exc)
            self._record(
                MessageRole.USER,
                [Text(text=f"That did not match the schema: {exc}. Reply with JSON only.")],
            )
            return PENDING
        if final:
            return Exhausted(value=value, summary=text[:SUMMARY_CHARS], spent=self._spent())
        return Completed(value=value, summary=text[:SUMMARY_CHARS], spent=self._spent())

    def _evaluate_turn(self, reply: Reply, final: bool) -> Outcome | Pending:
        uses = [b for b in reply.blocks if isinstance(b, ToolUse)]
        if not uses:
            return self._finish_from_text(reply, final, "")
        from_uses = self._handle_uses(uses, final)
        if not isinstance(from_uses, Pending):
            return from_uses
        if final:
            return self._finish_from_text(reply, final, uses[0].arguments)
        return PENDING

    def run(self) -> Outcome:
        while True:
            final = self.remaining.turns_exhausted
            outstanding = self.children.outstanding()
            if final and outstanding:
                return Idling(summary="turns exhausted while children ran", spent=self._spent())
            declarations = self._declarations(final, outstanding)
            if final:
                self._prepare_final_turn()
            else:
                self.remaining = self.remaining.spend_turn()
            reply = self._complete(declarations, force_tool=SUBMIT if final else "")
            self._record(MessageRole.ASSISTANT, reply.blocks)
            outcome = self._evaluate_turn(reply, final)
            if not isinstance(outcome, Pending):
                return outcome
