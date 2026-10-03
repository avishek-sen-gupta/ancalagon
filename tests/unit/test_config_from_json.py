import collections.abc
import json
import pathlib
import tomllib

import pytest

from ancalagon.config.from_json import config_from_json, document_on_stdin
from ancalagon.config.load import load_config
from ancalagon.fs.real_file_system import RealFileSystem

TOML = """
[workspace]
home = "./ws"
write_roots = ["./notes"]
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

[log]
socket = "/tmp/anc.sock"

[web]
allowed_domains = ["*.example.com"]

[roles.analyst]
profile = { module = "ancalagon.profiles.answering", name = "Answering" }
behaviour = "Analyse."
answer = { module = "shapekit.shapes", name = "Component" }
tools = ["read_file", "delegate_scout", "submit_answer"]
budget = { turns = 12, tool_calls = 30 }

[roles.analyst.before]
submit_answer = [{ module = "shapekit.shapes", name = "always_fine" }]

[roles.scout]
profile = { module = "ancalagon.profiles.answering", name = "Answering" }
behaviour = "Investigate."
tools = ["read_file", "submit_answer"]
budget = { turns = "infinite", tool_calls = 8 }

[run]
goal_file = "./goal.md"
input_file = ""
role = "analyst"
"""

KIT = """
import pydantic

from ancalagon.contracts.free_text import FreeText


class Component(pydantic.BaseModel, frozen=True):
    name: str


def always_fine(answer: FreeText) -> str:
    return ""
"""


def _document(extra: dict[str, str]) -> str:
    return json.dumps({**tomllib.loads(TOML), **extra})


class _Terminal:
    def isatty(self) -> bool:
        return True

    def read(self) -> str:
        raise AssertionError("a terminal must be refused before it is read")


class _Pipe:
    def __init__(self, text: str) -> None:
        self._text = text

    def isatty(self) -> bool:
        return False

    def read(self) -> str:
        return self._text


def test_the_json_reader_and_the_toml_reader_agree_on_one_document(
    tmp_path: pathlib.Path, importable: collections.abc.Callable[[pathlib.Path], None]
):
    package = tmp_path / "shapekit"
    package.mkdir()
    (package / "__init__.py").write_text("")
    (package / "shapes.py").write_text(KIT)
    importable(tmp_path)
    (tmp_path / "config.toml").write_text(TOML)
    fs = RealFileSystem()

    from_toml = load_config(pathlib.PurePath(tmp_path / "config.toml"), fs)
    from_json = config_from_json(_document({"base": str(tmp_path)}), fs)

    assert from_json == from_toml


def test_a_document_states_an_absolute_base_that_is_a_directory(
    tmp_path: pathlib.Path, importable: collections.abc.Callable[[pathlib.Path], None]
):
    package = tmp_path / "shapekit"
    package.mkdir()
    (package / "__init__.py").write_text("")
    (package / "shapes.py").write_text(KIT)
    importable(tmp_path)
    fs = RealFileSystem()

    with pytest.raises(ValueError, match="states its base"):
        config_from_json(_document({}), fs)

    with pytest.raises(ValueError, match="must be absolute"):
        config_from_json(_document({"base": "./ws"}), fs)

    absent = tmp_path / "nowhere"
    with pytest.raises(ValueError, match="not a directory"):
        config_from_json(_document({"base": str(absent)}), fs)


def test_reading_a_document_from_a_terminal_is_refused_rather_than_blocking():
    with pytest.raises(ValueError, match="pipe the document"):
        document_on_stdin(_Terminal())


def test_a_piped_document_is_read_whole():
    assert document_on_stdin(_Pipe('{"base": "/x"}')) == '{"base": "/x"}'
