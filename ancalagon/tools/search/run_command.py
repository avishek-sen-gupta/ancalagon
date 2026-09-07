# Runs an external tool and captures its output.
import collections.abc
import subprocess

from ancalagon.text.decoded import decoded


def run_command(command: collections.abc.Sequence[str], stdin: str = "") -> tuple[int, str, str]:
    completed = subprocess.run(command, input=stdin.encode("utf-8"), capture_output=True)
    return completed.returncode, decoded(completed.stdout), decoded(completed.stderr)
