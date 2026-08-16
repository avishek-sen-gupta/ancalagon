# Answers a subagent that stopped to ask something, which queues it to continue.
import pathlib

from ancalagon.answer import answer_task
from ancalagon.clock.clock import Clock
from ancalagon.contracts.tool_result import ToolResult
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

    def __init__(self, run_dir: pathlib.Path, parent: int, clock: Clock):
        self.run_dir = run_dir
        self.parent = parent
        self.clock = clock

    def run(self, args: AnswerArgs, ctx: ToolContext) -> ToolResult:
        try:
            resumed = answer_task(
                self.run_dir, args.task, args.answer, answered_by=self.parent, clock=self.clock
            )
        except (KeyError, ValueError) as exc:
            return ctx.failure(self.name, str(exc))
        return ctx.result(self.name, f"answered agent {args.task}; queued agent {resumed}")
