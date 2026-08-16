import pathlib

import pytest

from ancalagon.config.load import load_config
from ancalagon.sandbox.strategy import Strategy

TEMPLATE = """
[workspace]
write_root = "./ws"
read_roots = ["./artifacts"]

[agent]
root_behaviour = "You investigate."

[model]
name = "some-provider/some-model"
num_retries = 2
request_timeout_s = 120
max_tokens = 4000
allowed_domains = ["bedrock-runtime.us-east-1.amazonaws.com"]

[budget]
turns = 4
tool_calls = 8

[limits]
max_concurrent_agents = 1
agent_timeout_s = 300
max_depth = 1
compact_above_tokens = 60000
keep_recent_messages = 8
summary_chars = 1000

[tools]
enabled = []

[sandbox]
strategy = "fence"
{run}
"""


def _config_file(tmp_path: pathlib.Path, name: str, run: str) -> pathlib.Path:
    path = tmp_path / name
    path.write_text(TEMPLATE.format(run=run))
    return path


def test_run_settings_resolve_against_the_config_file(tmp_path: pathlib.Path):
    path = _config_file(
        tmp_path,
        "populated.toml",
        '[run]\nrun_dir = "./ws/runs/item"\ngoal_file = "./goal.md"\n'
        'contract_module = "./shape.py"\ncontract_class = "Answer"\n',
    )

    settings = load_config(path).run

    assert settings.run_dir == str(tmp_path / "ws" / "runs" / "item")
    assert settings.goal_file == str(tmp_path / "goal.md")
    assert settings.contract_module == str(tmp_path / "shape.py")
    assert settings.contract_class == "Answer"


def test_the_run_section_is_required_and_a_contract_must_name_a_class(
    tmp_path: pathlib.Path,
):
    blank = _config_file(
        tmp_path,
        "blank.toml",
        '[run]\nrun_dir = ""\ngoal_file = ""\ncontract_module = ""\ncontract_class = ""\n',
    )
    settings = load_config(blank).run
    assert (settings.run_dir, settings.goal_file, settings.contract_module) == ("", "", "")
    assert settings.contract_class == ""

    with pytest.raises(KeyError):
        load_config(_config_file(tmp_path, "absent.toml", ""))

    with pytest.raises(KeyError):
        load_config(
            _config_file(
                tmp_path,
                "partial.toml",
                '[run]\nrun_dir = ""\ngoal_file = ""\ncontract_module = ""\n',
            )
        )

    with pytest.raises(ValueError):
        load_config(
            _config_file(
                tmp_path,
                "classless.toml",
                '[run]\nrun_dir = ""\ngoal_file = ""\ncontract_module = "./shape.py"\ncontract_class = ""\n',
            )
        )


def test_the_sandbox_strategy_and_its_domains_come_from_the_config(tmp_path: pathlib.Path):
    path = _config_file(
        tmp_path,
        "sandboxed.toml",
        '[run]\nrun_dir = ""\ngoal_file = ""\ncontract_module = ""\ncontract_class = ""\n',
    )
    config = load_config(path)

    assert config.sandbox is Strategy.FENCE
    assert config.allowed_domains == ("bedrock-runtime.us-east-1.amazonaws.com",)
