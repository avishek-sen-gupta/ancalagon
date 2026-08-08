import json
import pathlib
import tomllib

import pytest

from ancalagon.config.config import Config
from ancalagon.config.load import load_config
from ancalagon.contracts.budget import Budget
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

[agent]
root_behaviour = "You investigate."

[model]
name = "claude-opus-5"
num_retries = 3
request_timeout_s = 300
max_tokens = 8000

[budget]
turns = 20
tool_calls = 60

[limits]
max_concurrent_agents = 1
agent_timeout_s = 3600
max_depth = 1
compact_above_tokens = 60000
keep_recent_messages = 8
summary_chars = 1000

[tools]
enabled = ["read_file", "ripgrep"]
""")
    config = load_config(config_path)
    assert config.write_root == write_root
    assert config.read_roots == (read_only,)
    assert config.root_behaviour == "You investigate."
    assert config.model == "claude-opus-5"
    assert config.num_retries == 3
    assert config.request_timeout_s == 300
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

[agent]
root_behaviour = "You investigate."

[model]
name = "claude-opus-5"
num_retries = 3
request_timeout_s = 300
max_tokens = 8000

[budget]
turns = 20
tool_calls = 60

[limits]
max_concurrent_agents = 4
agent_timeout_s = 3600
max_depth = 1
compact_above_tokens = 60000
keep_recent_messages = 8
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


def test_tilde_and_relative_roots_resolve_against_home_and_the_config_file(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
):
    home = tmp_path / "home"
    (home / "artifacts").mkdir(parents=True)
    monkeypatch.setenv("HOME", str(home))

    project = tmp_path / "project"
    (project / "ws").mkdir(parents=True)
    config_path = project / "ancalagon.toml"
    config_path.write_text("""
[workspace]
write_root = "./ws"
read_roots = ["~/artifacts"]

[agent]
root_behaviour = "You investigate."

[model]
name = "claude-opus-5"
num_retries = 3
request_timeout_s = 300
max_tokens = 8000

[budget]
turns = 20
tool_calls = 60

[limits]
max_concurrent_agents = 4
agent_timeout_s = 3600
max_depth = 1
compact_above_tokens = 60000
keep_recent_messages = 8
summary_chars = 1000

[tools]
enabled = []
""")
    monkeypatch.chdir(tmp_path)
    config = load_config(config_path)
    assert config.write_root == (project / "ws").resolve()
    assert config.read_roots == ((home / "artifacts").resolve(),)

    workspace = Workspace.from_config(config)
    wanted = home / "artifacts" / "graph.json"
    wanted.write_text("{}")
    assert workspace.resolve_read(pathlib.Path("~/artifacts/graph.json")) == wanted.resolve()


def test_config_needs_three_fields_in_code_but_a_complete_file_on_disk(
    tmp_path: pathlib.Path,
):
    minimal = Config(write_root=tmp_path, read_roots=(tmp_path,), model="bedrock/some-model")
    assert minimal.budget == Budget(turns=20, tool_calls=60)
    assert minimal.max_concurrent_agents == 4
    assert minimal.compact_above_tokens == 60000
    assert "prefer evidence from the files" in minimal.root_behaviour
    assert minimal.tools == []

    assert (
        Config(
            write_root=tmp_path,
            read_roots=(tmp_path,),
            model="m",
            budget=Budget(turns=200, tool_calls=500),
        ).budget.turns
        == 200
    )

    example = tomllib.loads(pathlib.Path("ancalagon.example.toml").read_text())
    for section, key in (
        ("limits", "summary_chars"),
        ("model", "num_retries"),
        ("agent", "root_behaviour"),
    ):
        broken = tmp_path / f"missing-{key}.toml"
        trimmed = {k: dict(v) for k, v in example.items()}
        del trimmed[section][key]
        broken.write_text(_toml(trimmed, tmp_path))
        with pytest.raises(KeyError):
            load_config(broken)


def _toml(data: dict[str, dict[str, object]], root: pathlib.Path) -> str:
    lines: list[str] = []
    for section, body in data.items():
        lines.append(f"[{section}]")
        for key, value in body.items():
            if key in ("write_root",):
                value = str(root)
            if key == "read_roots":
                value = [str(root)]
            lines.append(f"{key} = {json.dumps(value)}")
        lines.append("")
    return "\n".join(lines)
