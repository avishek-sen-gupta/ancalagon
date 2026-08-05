# Runs an external tool and captures its output.
import subprocess


def run_command(command: list[str], stdin: str = "") -> tuple[int, str, str]:
    completed = subprocess.run(command, input=stdin, capture_output=True, text=True)
    return completed.returncode, completed.stdout, completed.stderr
