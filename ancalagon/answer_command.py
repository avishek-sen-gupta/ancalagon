# The answer subcommand: unsticks an agent that stopped with a question.
import pathlib
import sys

from ancalagon.answer import answer_task
from ancalagon.bus.bus import HUMAN


def answer_command(run_dir: pathlib.Path, agent: int, answer: str) -> int:
    resumed = answer_task(run_dir, agent, answer, answered_by=HUMAN)
    sys.stdout.write(f"answered agent {agent}; queued agent {resumed}\n")
    return 0
