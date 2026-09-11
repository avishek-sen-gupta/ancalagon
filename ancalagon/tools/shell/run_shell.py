# Runs a command line through the shell, bounded by a timeout.
import logging
import pathlib
import subprocess

from ancalagon.text.decoded import decoded
from ancalagon.tools.shell.execution import Execution
from ancalagon.tools.shell.timed_out import TimedOut

LOGGER = logging.getLogger(__name__)


def run_shell(command: str, cwd: pathlib.PurePath, timeout_s: int) -> Execution | TimedOut:
    try:
        completed = subprocess.run(
            command,
            shell=True,
            cwd=cwd,
            input=b"",
            capture_output=True,
            timeout=timeout_s,
        )
    except subprocess.TimeoutExpired:
        LOGGER.exception("a shell command timed out")
        return TimedOut(seconds=timeout_s)
    return Execution(
        exit_code=completed.returncode,
        stdout=decoded(completed.stdout),
        stderr=decoded(completed.stderr),
    )
