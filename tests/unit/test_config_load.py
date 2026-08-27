import collections.abc
import pathlib

import pydantic
import pytest

from ancalagon.config.load import load_config
from ancalagon.contracts.budget import Budget
from ancalagon.contracts.class_ref import ClassRef
from ancalagon.contracts.function_ref import FunctionRef
from ancalagon.contracts.no_run import NO_RUN
from ancalagon.contracts.role import FREE_TEXT
from ancalagon.fs.real_file_system import RealFileSystem
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

REQUIRED_RUN = '[run]\ngoal_file = ""\ninput_file = ""\nrole = "scout"\n'


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
        '[run]\ngoal_file = "./goal.md"\n' 'input_file = "./input.json"\nrole = "analyst"\n',
    )

    settings = load_config(path, RealFileSystem()).run

    assert settings.goal_file == str(tmp_path / "goal.md")
    assert settings.input_file == str(tmp_path / "input.json")
    assert settings.role == "analyst"


def test_the_run_section_is_required_and_names_its_fields(
    tmp_path: pathlib.Path,
):
    blank = _config_file(
        tmp_path,
        "blank.toml",
        '[run]\ngoal_file = ""\ninput_file = ""\nrole = ""\n',
    )
    settings = load_config(blank, RealFileSystem()).run
    assert (settings.goal_file, settings.input_file) == ("", "")
    assert settings.role == ""

    with pytest.raises(KeyError):
        load_config(_config_file(tmp_path, "absent.toml", ""), RealFileSystem())

    with pytest.raises(KeyError):
        load_config(
            _config_file(
                tmp_path,
                "partial.toml",
                '[run]\ngoal_file = ""\ninput_file = ""\n',
            ),
            fs=RealFileSystem(),
        )


def test_the_sandbox_strategy_and_its_domains_come_from_the_config(tmp_path: pathlib.Path):
    path = _config_file(
        tmp_path,
        "sandboxed.toml",
        '[run]\ngoal_file = ""\ninput_file = ""\nrole = "scout"\n',
    )
    config = load_config(path, RealFileSystem())

    assert config.sandbox is Strategy.FENCE
    assert config.allowed_domains == ("bedrock-runtime.us-east-1.amazonaws.com",)


def test_roles_load_with_their_contracts_and_prose_is_the_absent_default(
    tmp_path: pathlib.Path, importable: collections.abc.Callable[[pathlib.Path], None]
):
    package = tmp_path / "shapekit"
    package.mkdir()
    (package / "__init__.py").write_text("")
    (package / "shapes.py").write_text(
        "import pydantic\n\n\nclass Component(pydantic.BaseModel):\n    name: str\n"
    )
    importable(tmp_path)
    config = _written(
        tmp_path,
        """
[roles.analyst]
behaviour = "Analyse."
answer = { module = "shapekit.shapes", name = "Component" }
tools = ["read_file", "delegate_scout"]
budget = { turns = 12, tool_calls = 30 }

[roles.scout]
behaviour = "Investigate."
tools = ["read_file"]
budget = { turns = 4, tool_calls = 8 }
""",
    )

    roles = load_config(config, RealFileSystem()).roles

    assert sorted(roles) == ["analyst", "scout"]
    assert roles["analyst"].behaviour == "Analyse."
    assert roles["analyst"].answer == ClassRef(module="shapekit.shapes", name="Component")
    assert roles["analyst"].tools == ("read_file", "delegate_scout")
    assert roles["analyst"].budget == Budget(turns=12, tool_calls=30)
    assert roles["scout"].answer == FREE_TEXT
    assert roles["scout"].input == FREE_TEXT

    spaced = tmp_path / "spaced.toml"
    spaced.write_text(
        TEMPLATE.format(
            run=REQUIRED_RUN,
            block='[roles."field scout"]\nbehaviour = "Look."\ntools = []\n'
            "budget = { turns = 4, tool_calls = 8 }\n",
        )
    )
    with pytest.raises(ValueError, match=r"\[roles.field scout\]"):
        load_config(spaced, RealFileSystem())


def test_a_config_naming_a_file_path_is_refused_at_load(tmp_path: pathlib.Path):
    config = _written(
        tmp_path,
        """
[roles.analyst]
behaviour = "Analyse."
answer = { module = "./shapes.py", name = "Component" }
tools = ["read_file"]
budget = { turns = 12, tool_calls = 30 }
""",
    )

    with pytest.raises(pydantic.ValidationError, match="module"):
        load_config(config, RealFileSystem())


RUNNERS = """
import pydantic


class Given(pydantic.BaseModel, frozen=True):
    path: str


class Produced(pydantic.BaseModel, frozen=True):
    at: float


def good(given: Given, ctx: pydantic.BaseModel) -> Produced:
    return Produced(at=1.0)


def one_parameter(given: Given) -> Produced:
    return Produced(at=1.0)


def bare(given, ctx) -> Produced:
    return Produced(at=1.0)


def not_a_model(given: int, ctx: pydantic.BaseModel) -> Produced:
    return Produced(at=1.0)


def no_return(given: Given, ctx: pydantic.BaseModel):
    return Produced(at=1.0)


def returns_a_scalar(given: Given, ctx: pydantic.BaseModel) -> int:
    return 1
"""


def _with_run(tmp_path: pathlib.Path, name: str, extra: str = "") -> pathlib.Path:
    return _written(
        tmp_path,
        f"""
[roles.transformer]
behaviour = "Transform it."
run = {{ module = "runkit.runners", name = "{name}" }}
tools = []
budget = {{ turns = 0, tool_calls = 0 }}
{extra}
""",
    )


def test_a_role_naming_a_run_function_takes_its_contracts_from_the_signature(
    tmp_path: pathlib.Path, importable: collections.abc.Callable[[pathlib.Path], None]
):
    package = tmp_path / "runkit"
    package.mkdir()
    (package / "__init__.py").write_text("")
    (package / "runners.py").write_text(RUNNERS)
    importable(tmp_path)

    role = load_config(_with_run(tmp_path, "good"), RealFileSystem()).roles["transformer"]

    assert role.run == FunctionRef(module="runkit.runners", name="good")
    assert role.input == ClassRef(module="runkit.runners", name="Given")
    assert role.answer == ClassRef(module="runkit.runners", name="Produced")

    prose = load_config(_written(tmp_path, PROSE_ROLE), RealFileSystem()).roles["scout"]
    assert prose.run == NO_RUN
    assert prose.input == FREE_TEXT

    def fault(name: str) -> str:
        with pytest.raises(ValueError) as raised:
            load_config(_with_run(tmp_path, name), RealFileSystem())
        return str(raised.value)

    assert fault("one_parameter") == (
        "one_parameter in runkit.runners must take 2 positional parameters, not ['given']"
    )
    assert "does not annotate its first parameter, given" in fault("bare")
    assert "annotates given as <class 'int'>, which is not a model class" in fault("not_a_model")
    assert "does not annotate its return" in fault("no_return")
    assert "annotates return as <class 'int'>, which is not a model class" in fault(
        "returns_a_scalar"
    )

    both = _with_run(
        tmp_path, "good", extra='answer = { module = "runkit.runners", name = "Produced" }'
    )
    with pytest.raises(ValueError, match="declares run"):
        load_config(both, RealFileSystem())


PROSE_ROLE = """
[roles.scout]
behaviour = "Investigate."
tools = ["read_file"]
budget = { turns = 4, tool_calls = 8 }
"""
