# Answers a subagent that stopped to ask something, which queues it to continue.
from ancalagon.answer import answer_task
from ancalagon.bus.bus import Bus
from ancalagon.clock.clock import Clock
from ancalagon.contracts.tool_result import ToolResult
from ancalagon.fs.file_system import FileSystem
from ancalagon.tools.delegate.answer_args import AnswerArgs
from ancalagon.tools.registry.tool import Tool
from ancalagon.tools.registry.tool_context import ToolContext


class AnswerTask(Tool[AnswerArgs]):
    name = "answer_task"
    description = (
        "Answer a task that stopped with a question, so it continues from where it "
        "left off with your answer and everything it had already worked out. Read the "
        "question with check_task first. Only a task that is waiting can be answered."
    )
    cost = 1
    args_model = AnswerArgs

    def __init__(self, bus: Bus, parent: int, clock: Clock, fs: FileSystem):
        self.bus = bus
        self.parent = parent
        self.clock = clock
        self.fs = fs

    def run(self, args: AnswerArgs, ctx: ToolContext) -> ToolResult:
        try:
            resumed = answer_task(
                self.bus,
                args.task,
                args.answer,
                answered_by=self.parent,
                clock=self.clock,
                fs=self.fs,
            )
        except KeyError as no_agent:
            return ctx.failure(self.name, str(no_agent.args[0]))
        except ValueError as refusal:
            return ctx.failure(self.name, str(refusal))
        return ctx.result(self.name, f"answered agent {args.task}; queued agent {resumed.id}")
