import os
import pathlib

from ancalagon.clock.fake_clock import FakeClock
from ancalagon.contracts.message import Message
from ancalagon.contracts.message_role import MessageRole
from ancalagon.contracts.text import Text
from ancalagon.contracts.tool_result_block import ToolResultBlock
from ancalagon.contracts.tool_use import ToolUse
from ancalagon.fs.real_file_system import RealFileSystem
from ancalagon.watch_command import concern, watching
from ancalagon.watching.rendered import TEXT_WIDTHS, rendered
from ancalagon.watching.watch import Watch

CYAN = "[36m"
YELLOW = "[1;33m"
RED = "[31m"
OFF = "[0m"
AGE_STEP = 2.0
COLUMNS = 80


def _message(role: MessageRole, blocks: list[Text | ToolUse | ToolResultBlock], agent: int = 3):
    return Message(role=role, blocks=blocks, agent=agent, seq=7, ts="2026-09-12T10:00:00Z")


def test_a_message_renders_a_header_and_one_line_per_block():
    message = _message(
        MessageRole.ASSISTANT,
        [
            Text(text="looking now"),
            ToolUse(id="tu_0", name="read_file", arguments='{"path": "/w/a.md"}'),
            ToolResultBlock(tool_use_id="tu_0", content="payload", is_error=False),
            ToolResultBlock(tool_use_id="tu_1", content="outside the read roots", is_error=True),
        ],
    )

    lines = rendered("r_1/root", message, 40).splitlines()

    assert lines[0] == f"{CYAN}[r_1/root/3]{OFF} A"
    assert lines[1] == "  looking now"
    assert lines[2] == f'  → {YELLOW}read_file{OFF} {{"path": "/w/a.md"}}'
    assert lines[3] == "  ← payload"
    assert lines[4] == f"  ← {RED}ERR{OFF} outside the read roots"
    assert len(lines) == 5


def test_a_message_indents_wrapped_text_and_truncates_every_block():
    message = _message(
        MessageRole.USER,
        [
            Text(text="first\nsecond"),
            Text(text="x" * 500),
            ToolUse(id="t", name="shell", arguments="y\ny" + "y" * 500),
            ToolResultBlock(tool_use_id="t", content="z\nz" + "z" * 500),
        ],
        agent=1,
    )

    lines = rendered("r_1/root", message, 10).splitlines()

    assert lines[0] == f"{CYAN}[r_1/root/1]{OFF} U"
    assert lines[1] == "  first"
    assert lines[2] == "  second"
    assert lines[3] == "  " + "x" * 40
    assert lines[4] == f"  → {YELLOW}shell{OFF} y y" + "y" * 500
    assert lines[5] == "  ← z z" + "z" * 7


def _write(tmp_path: pathlib.Path, run: str, task: str, messages: list[Message]) -> pathlib.Path:
    path = tmp_path / "runs" / run / "tasks" / task / "transcript.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as handle:
        handle.write("".join(m.model_dump_json() + "\n" for m in messages))
    _age(path)
    return path


def _age(path: pathlib.Path) -> None:
    stamp = os.stat(path).st_mtime + AGE_STEP
    os.utime(path, (stamp, stamp))


def _said(seq: int, what: str, agent: int = 1) -> Message:
    return Message(
        role=MessageRole.ASSISTANT,
        blocks=[Text(text=what)],
        agent=agent,
        seq=seq,
        ts="2026-09-12T10:00:00Z",
    )


def _watch(tmp_path: pathlib.Path) -> Watch:
    return Watch(pathlib.PurePath(tmp_path), RealFileSystem(), FakeClock(), COLUMNS)


def test_agents_already_on_disk_show_nothing_of_their_history(tmp_path: pathlib.Path):
    _write(tmp_path, "r_1", "root", [_said(1, "old news")])

    assert _watch(tmp_path).tick() == ""


def test_an_agent_that_appears_later_is_shown_from_its_first_message(tmp_path: pathlib.Path):
    watch = _watch(tmp_path)
    assert watch.tick() == ""
    _write(tmp_path, "r_1", "root", [_said(1, "hello")])

    shown = watch.tick()

    assert "hello" in shown
    assert f"{CYAN}[r_1/root/1]{OFF} A" in shown


def test_a_tick_shows_only_what_arrived_since_the_last_one(tmp_path: pathlib.Path):
    watch = _watch(tmp_path)
    watch.tick()
    _write(tmp_path, "r_1", "root", [_said(1, "first")])
    assert "first" in watch.tick()
    _write(tmp_path, "r_1", "root", [_said(2, "second")])

    shown = watch.tick()

    assert "second" in shown
    assert "first" not in shown
    assert watch.tick() == ""


def test_every_agent_in_every_run_is_followed(tmp_path: pathlib.Path):
    watch = _watch(tmp_path)
    watch.tick()
    _write(tmp_path, "r_1", "root", [_said(1, "from root")])
    _write(tmp_path, "r_1", "child", [_said(1, "from child", agent=2)])
    _write(tmp_path, "r_2", "root", [_said(1, "from another run")])

    shown = watch.tick()

    assert f"{CYAN}[r_1/root/1]{OFF}" in shown
    assert f"{CYAN}[r_1/child/2]{OFF}" in shown
    assert f"{CYAN}[r_2/root/1]{OFF}" in shown


class CountingFileSystem(RealFileSystem):
    def __init__(self):
        self.reads: list[str] = []

    def read_text(self, path: pathlib.PurePath) -> str:
        self.reads = [*self.reads, str(path)]
        return super().read_text(path)


def test_a_transcript_that_has_not_changed_is_not_read_again(tmp_path: pathlib.Path):
    _write(tmp_path, "r_1", "root", [_said(1, "settled")])
    fs = CountingFileSystem()
    watch = Watch(pathlib.PurePath(tmp_path), fs, FakeClock(), COLUMNS)
    after_startup = len(fs.reads)

    assert watch.tick() == ""
    assert watch.tick() == ""
    assert len(fs.reads) == after_startup

    _write(tmp_path, "r_1", "root", [_said(2, "moved")])
    assert "moved" in watch.tick()
    assert len(fs.reads) == after_startup + 1


def test_the_command_watches_the_write_root_its_config_names(tmp_path: pathlib.Path):
    config = tmp_path / "nested" / "some.toml"
    config.parent.mkdir(parents=True, exist_ok=True)
    config.write_text(CONFIG)

    watch = watching(pathlib.PurePath(config), RealFileSystem(), FakeClock())

    assert watch.write_root == pathlib.PurePath(tmp_path / "nested" / "ws")
    assert watch.tick() == ""


CONFIG = """
[workspace]
write_root = "./ws"
read_roots = ["./ws"]

[model]
name = "some-provider/some-model"
num_retries = 2
request_timeout_s = 120
max_tokens = 4000
allowed_domains = []

[limits]
max_concurrent_agents = 1
agent_timeout_s = 300
max_depth = 1
compact_above_tokens = 60000
keep_recent_messages = 8
summary_chars = 1000

[sandbox]
strategy = "fence"

[run]
goal_file = ""
input_file = ""
role = "solo"

[roles.solo]
behaviour = "Answer it."
tools = ["submit_answer"]

[roles.solo.budget]
turns = 1
tool_calls = 1
"""


def test_the_text_budget_shrinks_with_the_label_it_shares_a_line_with(tmp_path: pathlib.Path):
    watch = _watch(tmp_path)
    watch.tick()
    _write(tmp_path, "r", "a", [_said(1, "t" * 4000)])
    _write(tmp_path, "a_very_long_run_name", "a_very_long_task_name", [_said(1, "t" * 4000)])

    budgets = sorted(len(ln) for ln in watch.tick().splitlines() if ln.startswith("  t"))

    room = len("a_very_long_run_name/a_very_long_task_name") - len("r/a")
    assert budgets[1] - budgets[0] == room * TEXT_WIDTHS


def test_a_write_root_that_holds_no_runs_directory_is_called_out(tmp_path: pathlib.Path):
    fs = RealFileSystem()
    missing = pathlib.PurePath(tmp_path / "never-made")
    bare = pathlib.PurePath(tmp_path / "bare")
    fs.mkdir(bare, parents=True, exist_ok=True)
    workspace = pathlib.PurePath(tmp_path / "ws")
    fs.mkdir(workspace / "runs", parents=True, exist_ok=True)

    assert concern(missing, fs) == f"no runs directory under {missing}; is this the write_root?"
    assert concern(bare, fs) == f"no runs directory under {bare}; is this the write_root?"
    assert concern(workspace, fs) == ""
