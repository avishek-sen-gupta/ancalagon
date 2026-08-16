# The only place in the codebase that starts an OS process.
import os
import pathlib
import subprocess
import sys

from ancalagon.sandbox.sandbox import Sandbox
from ancalagon.sandbox.unsandboxed import UNSANDBOXED
from ancalagon.supervisor.process import Process
from ancalagon.supervisor.spawner import Spawner


class SubprocessSpawner(Spawner):
    def __init__(
        self,
        run_dir: pathlib.Path,
        config_path: pathlib.Path,
        sandbox: Sandbox = UNSANDBOXED,
    ):
        self.run_dir = run_dir
        self.config_path = config_path
        self.sandbox = sandbox

    def spawn(self, task_dir: pathlib.Path, agent_id: int) -> Process:
        stderr = task_dir / f"stderr-{agent_id}.log"
        stderr.parent.mkdir(parents=True, exist_ok=True)
        command = [
            sys.executable,
            "-m",
            "ancalagon.worker",
            "--run-dir",
            str(self.run_dir),
            "--dir",
            str(task_dir),
            "--agent-id",
            str(agent_id),
            "--config",
            str(self.config_path),
        ]
        return subprocess.Popen(
            list(self.sandbox.wrap(command)),
            stdout=subprocess.DEVNULL,
            stderr=stderr.open("w"),
            cwd=self.run_dir,
            env={**os.environ, **self.sandbox.environment()},
        )
