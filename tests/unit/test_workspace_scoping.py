import pathlib

import pytest

from ancalagon.config.config import Config
from ancalagon.fs.real_file_system import RealFileSystem
from ancalagon.config.load import load_config
from ancalagon.tools.registry.tool_context import ToolContext
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

    ws = Workspace(RealFileSystem(), write_root=write_root, read_roots=(read_only, write_root))

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

    inside = ToolContext(
        workspace=ws, output_dir=write_root / "tools", summary_chars=10, agent_id=1
    )
    written = inside.result("read_file", "hello")
    assert written.path == (write_root / "tools" / "0000-read_file.txt").resolve()
    assert written.path.read_text() == "hello"

    escaping = ToolContext(workspace=ws, output_dir=outside / "tools", summary_chars=10, agent_id=1)
    with pytest.raises(ScopeError):
        escaping.result("read_file", "hello")
    assert not (outside / "tools").exists()

    config_path = tmp_path / "ancalagon.toml"
    config_path.write_text(f"""
[workspace]
write_root = "{write_root}"
read_roots = ["{read_only}"]

[model]
name = "claude-opus-5"
num_retries = 3
request_timeout_s = 300
max_tokens = 8000
allowed_domains = []

[limits]
max_concurrent_agents = 1
agent_timeout_s = 3600
max_depth = 1
compact_above_tokens = 60000
keep_recent_messages = 8
summary_chars = 1000

[sandbox]
strategy = "none"

[run]
goal_file = ""
input_file = ""
role = ""
""")
    config = load_config(config_path)
    assert config.write_root == write_root
    assert config.read_roots == (read_only,)
    assert config.model == "claude-opus-5"
    assert config.num_retries == 3
    assert config.request_timeout_s == 300
    assert config.max_concurrent_agents == 1
    assert config.agent_timeout_s == 3600
    assert (
        Workspace.from_config(config, RealFileSystem()).resolve_read(read_only / "a.txt").exists()
    )


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
num_retries = 3
request_timeout_s = 300
max_tokens = 8000
allowed_domains = []

[limits]
max_concurrent_agents = 4
agent_timeout_s = 3600
max_depth = 1
compact_above_tokens = 60000
keep_recent_messages = 8
summary_chars = 1000

[sandbox]
strategy = "none"

[run]
goal_file = ""
input_file = ""
role = ""
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

[model]
name = "claude-opus-5"
num_retries = 3
request_timeout_s = 300
max_tokens = 8000
allowed_domains = []

[limits]
max_concurrent_agents = 4
agent_timeout_s = 3600
max_depth = 1
compact_above_tokens = 60000
keep_recent_messages = 8
summary_chars = 1000

[sandbox]
strategy = "none"

[run]
goal_file = ""
input_file = ""
role = ""
""")
    monkeypatch.chdir(tmp_path)
    config = load_config(config_path)
    assert config.write_root == (project / "ws").resolve()
    assert config.read_roots == ((home / "artifacts").resolve(),)

    workspace = Workspace.from_config(config, RealFileSystem())
    wanted = home / "artifacts" / "graph.json"
    wanted.write_text("{}")
    assert workspace.resolve_read(pathlib.Path("~/artifacts/graph.json")) == wanted.resolve()


def test_config_needs_three_fields_in_code_but_a_complete_file_on_disk(
    tmp_path: pathlib.Path,
):
    minimal = Config(write_root=tmp_path, read_roots=(tmp_path,), model="bedrock/some-model")
    assert minimal.max_concurrent_agents == 4
    assert minimal.compact_above_tokens == 60000
    assert minimal.roles == {}

    assert (
        Config(
            write_root=tmp_path,
            read_roots=(tmp_path,),
            model="m",
            max_concurrent_agents=7,
        ).max_concurrent_agents
        == 7
    )

    example = pathlib.Path("ancalagon.example.toml").read_text()
    for section, key in (
        ("limits", "summary_chars"),
        ("model", "num_retries"),
        ("sandbox", "strategy"),
    ):
        broken = tmp_path / f"missing-{key}.toml"
        broken.write_text(_without_key(example, section, key))
        with pytest.raises(KeyError):
            load_config(broken)


def _without_key(text: str, section: str, key: str) -> str:
    blocks = text.split("\n\n")
    return "\n\n".join(
        (
            "\n".join(line for line in block.splitlines() if not line.startswith(f"{key} ="))
            if block.startswith(f"[{section}]")
            else block
        )
        for block in blocks
    )


def test_workspace_reads_and_writes_only_inside_its_roots(tmp_path: pathlib.Path):
    write_root = tmp_path / "ws"
    read_only = tmp_path / "artifacts"
    write_root.mkdir()
    read_only.mkdir()
    source = read_only / "given.txt"
    source.write_text("given", encoding="utf-8")
    outside = tmp_path / "outside.txt"
    outside.write_text("untouched", encoding="utf-8")

    workspace = Workspace(
        RealFileSystem(), write_root=write_root, read_roots=(read_only, write_root)
    )

    workspace.write_text(write_root / "in.txt", "fine")
    assert workspace.read_text(write_root / "in.txt") == "fine"
    assert workspace.read_text(source) == "given"

    with pytest.raises(ScopeError):
        workspace.write_text(source, "clobbered")
    assert source.read_text(encoding="utf-8") == "given"

    with pytest.raises(ScopeError):
        workspace.read_text(outside)
    with pytest.raises(ScopeError):
        workspace.write_text(outside, "clobbered")
    assert outside.read_text(encoding="utf-8") == "untouched"
