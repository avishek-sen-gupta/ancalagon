import pathlib

import pytest

from ancalagon.config.load import load_config
from ancalagon.workspace.scope_error import ScopeError
from ancalagon.workspace.workspace import Workspace


def test_scoping_rejects_every_escape_and_config_round_trips(tmp_path: pathlib.Path):
    write_root = tmp_path / "ws"
    read_only = tmp_path / "artifacts"
    outside = tmp_path / "elsewhere"
    for d in (write_root, read_only, outside):
        d.mkdir()
    (read_only / "a.txt").write_text("data")
    (outside / "secret.txt").write_text("nope")

    ws = Workspace(write_root=write_root, read_roots=(read_only, write_root))

    assert ws.resolve_write(write_root / "out.json") == (write_root / "out.json").resolve()
    assert ws.resolve_read(read_only / "a.txt") == (read_only / "a.txt").resolve()
    assert ws.resolve_read(write_root / "out.json") == (write_root / "out.json").resolve()

    with pytest.raises(ScopeError):
        ws.resolve_write(read_only / "a.txt")
    with pytest.raises(ScopeError):
        ws.resolve_read(outside / "secret.txt")
    with pytest.raises(ScopeError):
        ws.resolve_write(write_root / ".." / "elsewhere" / "x.txt")

    link = write_root / "escape"
    link.symlink_to(outside)
    with pytest.raises(ScopeError):
        ws.resolve_write(link / "secret.txt")

    config_path = tmp_path / "ancalagon.toml"
    config_path.write_text(f"""
[workspace]
write_root = "{write_root}"
read_roots = ["{read_only}"]

[model]
name = "claude-opus-5"
max_tokens = 8000

[budget]
turns = 20
tool_calls = 60

[limits]
max_concurrent_agents = 1
agent_timeout_s = 3600
max_depth = 1
summary_chars = 1000

[tools]
enabled = ["read_file", "ripgrep"]
""")
    config = load_config(config_path)
    assert config.write_root == write_root
    assert config.read_roots == (read_only,)
    assert config.model == "claude-opus-5"
    assert config.budget.turns == 20
    assert config.max_concurrent_agents == 1
    assert config.agent_timeout_s == 3600
    assert config.tools == ["read_file", "ripgrep"]
    assert Workspace.from_config(config).resolve_read(read_only / "a.txt").exists()


def test_config_resolves_relative_roots_against_the_config_file_not_the_cwd(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
):
    project = tmp_path / "project"
    (project / "ws").mkdir(parents=True)
    (project / "artifacts").mkdir()
    config_path = project / "ancalagon.toml"
    config_path.write_text("""
[workspace]
write_root = "./ws"
read_roots = ["./artifacts"]

[model]
name = "claude-opus-5"
max_tokens = 8000

[budget]
turns = 20
tool_calls = 60

[limits]
max_concurrent_agents = 4
agent_timeout_s = 3600
max_depth = 1
summary_chars = 1000

[tools]
enabled = []
""")
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)

    config = load_config(config_path)
    assert config.write_root == (project / "ws").resolve()
    assert config.read_roots == ((project / "artifacts").resolve(),)
