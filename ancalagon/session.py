import datetime
import logging

import pydantic

from ancalagon.contracts.block import Block
from ancalagon.contracts.budget import Budget
from ancalagon.contracts.completed import Completed
from ancalagon.contracts.exhausted import Exhausted
from ancalagon.contracts.failed import Failed
from ancalagon.contracts.message import Message
from ancalagon.contracts.needs_input import NeedsInput
from ancalagon.contracts.outcome import Outcome
from ancalagon.contracts.reply import Reply
from ancalagon.contracts.role import Role
from ancalagon.contracts.task_spec import TaskSpec
from ancalagon.contracts.text import Text
from ancalagon.contracts.tool_result_block import ToolResultBlock
from ancalagon.contracts.tool_use import ToolUse
from ancalagon.llm.llm import LLM
from ancalagon.tools.need_input.need_input import NeedInput
from ancalagon.tools.registry.registry import Registry
from ancalagon.tools.registry.tool_context import ToolContext
from ancalagon.transcript.transcript import Transcript

LOGGER = logging.getLogger(__name__)

FINAL_INSTRUCTION = (
    "Your budget is exhausted. Answer now from what you already know, "
    "as a single JSON object matching the required output schema. No tools are available."
)


class Session:
    def __init__(
        self,
        spec: TaskSpec,
        input_json: str,
        messages: list[Message],
        transcript: Transcript,
        agent_id: int,
        llm: LLM,
        registry: Registry,
        ctx: ToolContext,
        output_class: type[pydantic.BaseModel],
    ):
        self.spec = spec
        self.input_json = input_json
        self.messages = list(messages)
        self.transcript = transcript
        self.agent_id = agent_id
        self.llm = llm
        self.registry = registry
        self.ctx = ctx
        self.output_class = output_class
        self.remaining = spec.budget
        self.seq = len(messages)
        if not self.messages:
            self._record(Role.USER, [Text(text=f"{spec.goal}\n\nInput: {input_json}")])

    def _system(self) -> str:
        schema = self.output_class.model_json_schema()
        return (
            f"{self.spec.behaviour}\n\n"
            f"Goal: {self.spec.goal}\n\n"
            f"Input: {self.input_json}\n\n"
            f"When finished, reply with a single JSON object matching this schema "
            f"and nothing else: {schema}"
        )

    def _record(self, role: Role, blocks: list[Block]) -> None:
        message = Message(
            role=role,
            blocks=blocks,
            agent=self.agent_id,
            seq=self.seq,
            ts=datetime.datetime.now(datetime.UTC).isoformat(),
        )
        self.seq += 1
        self.messages.append(message)
        self.transcript.append(message)

    def _spent(self) -> Budget:
        return Budget(
            turns=self.spec.budget.turns - self.remaining.turns,
            tool_calls=self.spec.budget.tool_calls - self.remaining.tool_calls,
        )

    def _text_of(self, reply: Reply) -> str:
        return "".join(b.text for b in reply.blocks if isinstance(b, Text))

    def _run_tools(self, uses: list[ToolUse]) -> None:
        blocks: list[Block] = []
        for use in uses:
            if self.remaining.tool_calls_exhausted:
                blocks.append(
                    ToolResultBlock(
                        tool_use_id=use.id,
                        content="tool-call budget exhausted; this call was not run",
                        is_error=True,
                    )
                )
                continue
            self.remaining = self.remaining.spend_tool_call()
            try:
                result = self.registry.get(use.name).run(use.arguments, self.ctx)
            except Exception as exc:
                LOGGER.warning("tool %s raised: %s", use.name, exc)
                result = self.ctx.failure(use.name, f"{type(exc).__name__}: {exc}")
            blocks.append(
                ToolResultBlock(
                    tool_use_id=use.id,
                    content=f"{result.summary}\n[full output: {result.path}]",
                    is_error=not result.ok,
                )
            )
        self._record(Role.USER, blocks)

    def _question_asked(self) -> str:
        if "need_input" not in self.registry.names():
            return ""
        tool = self.registry.get("need_input")
        return tool.question if isinstance(tool, NeedInput) else ""

    def _final_turn(self) -> Outcome:
        if self.messages and self.messages[-1].role is Role.USER:
            self._record(Role.ASSISTANT, [Text(text="Understood.")])
        self._record(Role.USER, [Text(text=FINAL_INSTRUCTION)])
        reply = self.llm.complete(self._system(), self.messages, [])
        self._record(Role.ASSISTANT, reply.blocks)
        text = self._text_of(reply)
        try:
            value = self.output_class.model_validate_json(text)
        except pydantic.ValidationError as exc:
            return Failed(
                error=f"final answer did not validate: {exc}",
                summary=text[:200],
                spent=self._spent(),
            )
        return Exhausted(value=value, summary=text[:200], spent=self._spent())

    def run(self) -> Outcome:
        schemas = self.registry.schemas()
        while True:
            if self.remaining.turns_exhausted or self.remaining.tool_calls_exhausted:
                return self._final_turn()
            self.remaining = self.remaining.spend_turn()
            reply = self.llm.complete(self._system(), self.messages, schemas)
            self._record(Role.ASSISTANT, reply.blocks)
            uses = [b for b in reply.blocks if isinstance(b, ToolUse)]
            if uses:
                self._run_tools(uses)
                asked = self._question_asked()
                if asked:
                    return NeedsInput(question=asked, summary=asked[:200], spent=self._spent())
                continue
            text = self._text_of(reply)
            try:
                value = self.output_class.model_validate_json(text)
            except pydantic.ValidationError as exc:
                LOGGER.info("output did not validate, asking again: %s", exc)
                self._record(
                    Role.USER,
                    [Text(text=f"That did not match the schema: {exc}. Reply with JSON only.")],
                )
                continue
            return Completed(value=value, summary=text[:200], spent=self._spent())
