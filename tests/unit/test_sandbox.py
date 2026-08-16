import json
import pathlib

from ancalagon.sandbox.fence import Fence
from ancalagon.sandbox.unsandboxed import Unsandboxed


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
