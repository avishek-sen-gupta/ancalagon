from ancalagon.sandbox.unsandboxed import Unsandboxed


def test_the_unsandboxed_strategy_changes_neither_the_command_nor_the_environment():
    command = ["python", "-m", "ancalagon.worker", "--agent-id", "3"]

    assert list(Unsandboxed().wrap(command)) == command
    assert dict(Unsandboxed().environment()) == {}
