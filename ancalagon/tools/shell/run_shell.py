# Runs a command line through the shell, bounded by a timeout.
import pathlib
import subprocess

from ancalagon.tools.shell.execution import Execution
from ancalagon.tools.shell.timed_out import TimedOut


def run_shell(command: str, cwd: pathlib.PurePath, timeout_s: int) -> Execution | TimedOut:
    try:
        completed = subprocess.run(
            command,
            shell=True,
            cwd=cwd,
            input="",
            capture_output=True,
            text=True,
            timeout=timeout_s,
        )
    except subprocess.TimeoutExpired:
        return TimedOut(seconds=timeout_s)
    return Execution(
        exit_code=completed.returncode, stdout=completed.stdout, stderr=completed.stderr
    )
