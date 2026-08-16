import pathlib

import pytest

from ancalagon.config.load import load_config
from ancalagon.contracts.budget import Budget
from ancalagon.contracts.class_ref import ClassRef
from ancalagon.contracts.role import FREE_TEXT
from ancalagon.sandbox.strategy import Strategy

TEMPLATE = """
[workspace]
write_root = "./ws"
read_roots = ["./artifacts"]

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

[sandbox]
strategy = "fence"
{run}
{block}
"""

REQUIRED_RUN = '[run]\nrun_dir = ""\ngoal_file = ""\ncontract_module = ""\ncontract_class = ""\n'


def _config_file(tmp_path: pathlib.Path, name: str, run: str) -> pathlib.Path:
    path = tmp_path / name
    path.write_text(TEMPLATE.format(run=run, block=""))
    return path


def _written(tmp_path: pathlib.Path, block: str) -> pathlib.Path:
    path = tmp_path / "config.toml"
    path.write_text(TEMPLATE.format(run=REQUIRED_RUN, block=block))
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


def test_roles_load_with_their_contracts_and_prose_is_the_absent_default(tmp_path: pathlib.Path):
    shapes = tmp_path / "shapes.py"
    shapes.write_text("import pydantic\n\n\nclass Component(pydantic.BaseModel):\n    name: str\n")
    config = _written(
        tmp_path,
        """
[roles.analyst]
behaviour = "Analyse."
answer = { module = "./shapes.py", name = "Component" }
tools = ["read_file", "delegate_scout"]
budget = { turns = 12, tool_calls = 30 }

[roles.scout]
behaviour = "Investigate."
tools = ["read_file"]
budget = { turns = 4, tool_calls = 8 }
""",
    )

    roles = load_config(config).roles

    assert sorted(roles) == ["analyst", "scout"]
    assert roles["analyst"].behaviour == "Analyse."
    assert roles["analyst"].answer == ClassRef(module=str(shapes), name="Component")
    assert roles["analyst"].tools == ("read_file", "delegate_scout")
    assert roles["analyst"].budget == Budget(turns=12, tool_calls=30)
    assert roles["scout"].answer == FREE_TEXT
    assert roles["scout"].input == FREE_TEXT
