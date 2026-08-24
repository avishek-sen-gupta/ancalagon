import json
import pathlib

import pytest

from ancalagon.bus.lifecycle_store import LifecycleStore
from ancalagon.cli import main
from ancalagon.clock.system_clock import SystemClock
from ancalagon.contracts.agent_status import AgentStatus
from ancalagon.contracts.tool_use import ToolUse
from ancalagon.fs.real_file_system import RealFileSystem
from tests.integration.prepared_run import prepared_run_dir
from tests.integration.scripted_model import ScriptedModel

GOAL = "Say what the bus does."

HOOKS = """
from __future__ import annotations

from ancalagon.contracts.accepted import Accepted
from ancalagon.contracts.free_text import FreeText
from ancalagon.contracts.refused import Refused
from ancalagon.contracts.reviewed import Reviewed
from ancalagon.tools.registry.tool_context import ToolContext

SUBJECT = 3


def mentions_the_subject(answer: FreeText, ctx: ToolContext) -> Reviewed:
    asked = ctx.input
    if not isinstance(asked, FreeText):
        return Refused(reason="this role was given no goal to check against")
    wanted = asked.text.split()[SUBJECT].rstrip(".")
    if wanted not in answer.text:
        return Refused(reason=f"your answer must mention {wanted}")
    return Accepted(value=answer.model_copy(update={"text": answer.text.strip()}))
"""

CONFIG = """
[workspace]
write_root = "{write_root}"
read_roots = ["{write_root}"]

[model]
name = "openai/scripted"
num_retries = 0
request_timeout_s = 30
max_tokens = 512
allowed_domains = []

[limits]
max_concurrent_agents = 1
agent_timeout_s = 120
max_depth = 1
compact_above_tokens = 0
keep_recent_messages = 8
summary_chars = 400

[sandbox]
strategy = "none"

[roles.root]
behaviour = "You answer the goal."
tools = []

[roles.root.budget]
turns = 4
tool_calls = 8

[roles.root.before]
submit_answer = [{{ module = "{hooks}", name = "mentions_the_subject" }}]

[run]
goal_file = "{goal_file}"
input_file = ""
role = "root"
"""


def _config(tmp_path: pathlib.Path, hooks: pathlib.Path) -> pathlib.Path:
    write_root = tmp_path / "ws"
    write_root.mkdir(parents=True, exist_ok=True)
    goal_file = tmp_path / "goal.md"
    goal_file.write_text(GOAL)
    config = tmp_path / "ancalagon.toml"
    config.write_text(CONFIG.format(write_root=write_root, hooks=hooks, goal_file=goal_file))
    return config


def test_a_declared_hook_refuses_an_answer_in_a_real_worker_until_the_agent_fixes_it(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
):
    hooks = tmp_path / "hooks.py"
    hooks.write_text(HOOKS)
    run_dir = tmp_path / "ws" / "runs" / "hooked"
    submitted: list[str] = []

    def decide(goal: str, turn: int) -> list[ToolUse]:
        text = "  the bus is append only  " if turn else "no idea"
        submitted.append(text)
        return [ToolUse(id=f"s{turn}", name="submit_answer", arguments=json.dumps({"text": text}))]

    model = ScriptedModel(decide)
    monkeypatch.setenv("OPENAI_BASE_URL", model.base_url)
    monkeypatch.setenv("OPENAI_API_KEY", "scripted")

    try:
        assert main(_config(tmp_path, hooks), prepared_run_dir(run_dir)) == 0
    finally:
        model.close()

    assert submitted == ["no idea", "  the bus is append only  "]
    outcome = json.loads((run_dir / "tasks" / "root" / "outcome-1.json").read_text())
    assert outcome["kind"] == "completed"
    assert outcome["value"] == {"text": "the bus is append only"}

    bus = LifecycleStore.open(run_dir / "bus.db", SystemClock(), RealFileSystem())
    assert [e.status for e in bus.history(1)][-1] is AgentStatus.COMPLETED
