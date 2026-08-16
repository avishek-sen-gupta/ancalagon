import collections.abc
import json
import pathlib

from ancalagon.sandbox.fence import Fence
from ancalagon.sandbox.sandbox import Sandbox
from ancalagon.sandbox.unsandboxed import Unsandboxed
from ancalagon.supervisor.subprocess_spawner import SubprocessSpawner


def test_the_unsandboxed_strategy_changes_neither_the_command_nor_the_environment():
    command = ["python", "-m", "ancalagon.worker", "--agent-id", "3"]

    assert list(Unsandboxed().wrap(command)) == command
    assert dict(Unsandboxed().environment()) == {}


def test_fence_writes_its_policy_and_wraps_the_command(tmp_path: pathlib.Path):
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    write_root = tmp_path / "ws"

    sandbox = Fence(
        write_root=write_root,
        allowed_domains=["bedrock-runtime.us-east-1.amazonaws.com"],
        run_dir=run_dir,
    )

    policy = json.loads((run_dir / "fence.json").read_text())
    assert policy == {
        "network": {"allowedDomains": ["bedrock-runtime.us-east-1.amazonaws.com"]},
        "filesystem": {"allowWrite": [str(write_root)]},
    }

    assert list(sandbox.wrap(["python", "-m", "ancalagon.worker"])) == [
        "fence",
        "-s",
        str(run_dir / "fence.json"),
        "--",
        "python",
        "-m",
        "ancalagon.worker",
    ]
    assert dict(sandbox.environment()) == {"no_proxy": "", "NO_PROXY": ""}


class RecordingSandbox(Sandbox):
    def __init__(self) -> None:
        self.seen: list[str] = []

    def wrap(self, command: collections.abc.Sequence[str]) -> collections.abc.Sequence[str]:
        self.seen = list(command)
        return command

    def environment(self) -> collections.abc.Mapping[str, str]:
        return {"MARKER": "set"}


def test_the_spawner_wraps_the_worker_command_with_its_sandbox(tmp_path: pathlib.Path):
    sandbox = RecordingSandbox()
    spawner = SubprocessSpawner(run_dir=tmp_path, config_path=tmp_path / "c.toml", sandbox=sandbox)

    process = spawner.spawn(tmp_path / "tasks" / "root", agent_id=7)
    process.kill()

    assert sandbox.seen[1:3] == ["-m", "ancalagon.worker"]
    assert "--agent-id" in sandbox.seen
