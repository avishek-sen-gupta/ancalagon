# Runs an external tool and captures its output.
import collections.abc
import subprocess


def run_command(command: collections.abc.Sequence[str], stdin: str = "") -> tuple[int, str, str]:
    completed = subprocess.run(command, input=stdin, capture_output=True, text=True)
    return completed.returncode, completed.stdout, completed.stderr
