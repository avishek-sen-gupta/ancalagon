import pathlib

from ancalagon.config.config import Config
from ancalagon.config.load import load_config
from ancalagon.fs.real_file_system import RealFileSystem
from ancalagon.run import CONFIG

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

[run]
goal_file = ""
input_file = ""
role = "scout"
"""


def test_a_materialised_config_round_trips(tmp_path: pathlib.Path):
    source = tmp_path / "anc.toml"
    source.write_text(TEMPLATE)
    given = load_config(pathlib.PurePath(source), RealFileSystem())
    written = tmp_path / CONFIG
    written.write_text(given.model_dump_json())

    assert Config.model_validate_json(written.read_text()) == given
