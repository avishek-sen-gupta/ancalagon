import pathlib
import subprocess
import sys

from ancalagon.supervisor.process import Process


class SubprocessSpawner:
    def __init__(self, run_dir: pathlib.Path, config_path: pathlib.Path):
        self.run_dir = run_dir
        self.config_path = config_path

    def spawn(self, task_dir: pathlib.Path, agent_id: int) -> Process:
        stderr = task_dir / f"stderr-{agent_id}.log"
        stderr.parent.mkdir(parents=True, exist_ok=True)
        return subprocess.Popen(
            [
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
            ],
            stdout=subprocess.DEVNULL,
            stderr=stderr.open("w"),
            cwd=self.run_dir,
        )
