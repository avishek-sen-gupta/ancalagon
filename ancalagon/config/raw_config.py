# One config document exactly as TOML or JSON presents it, before paths are resolved.
import pydantic

from ancalagon.config.raw_role import RawRole
from ancalagon.sandbox.strategy import Strategy


class RawWorkspace(pydantic.BaseModel, frozen=True):
    home: str
    write_roots: list[str]
    read_roots: list[str]


class RawModel(pydantic.BaseModel, frozen=True):
    name: str
    custom_llm_provider: str = ""
    num_retries: int
    request_timeout_s: int
    max_tokens: int
    allowed_domains: list[str]


class RawLimits(pydantic.BaseModel, frozen=True):
    max_concurrent_agents: int
    agent_timeout_s: int
    max_depth: int
    compact_above_tokens: int
    keep_recent_messages: int
    summary_chars: int


class RawRun(pydantic.BaseModel, frozen=True):
    goal_file: str
    input_file: str
    role: str


class RawSandbox(pydantic.BaseModel, frozen=True):
    strategy: Strategy


class RawLog(pydantic.BaseModel, frozen=True):
    socket: str = ""


class RawWeb(pydantic.BaseModel, frozen=True):
    allowed_domains: list[str] = []


class RawConfig(pydantic.BaseModel, frozen=True):
    workspace: RawWorkspace
    model: RawModel
    limits: RawLimits
    run: RawRun
    sandbox: RawSandbox
    base: str = pydantic.Field(
        default="",
        description="Absolute directory relative paths resolve against, and the import anchor "
        "for dotted module refs. Required for a document on stdin; refused in a TOML file, "
        "whose own directory is used.",
    )
    log: RawLog = RawLog()
    web: RawWeb = RawWeb()
    roles: dict[str, RawRole] = {}
