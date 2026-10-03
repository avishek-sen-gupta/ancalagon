# One config document exactly as TOML or JSON presents it, before paths are resolved.
import pydantic

from ancalagon.config.role_from_config import RoleFromConfig
from ancalagon.sandbox.strategy import Strategy


class WorkspaceFromConfig(pydantic.BaseModel, frozen=True):
    home: str
    write_roots: list[str]
    read_roots: list[str]


class ModelFromConfig(pydantic.BaseModel, frozen=True):
    name: str
    custom_llm_provider: str = ""
    num_retries: int
    request_timeout_s: int
    max_tokens: int
    allowed_domains: list[str]


class LimitsFromConfig(pydantic.BaseModel, frozen=True):
    max_concurrent_agents: int
    agent_timeout_s: int
    max_depth: int
    compact_above_tokens: int
    keep_recent_messages: int
    summary_chars: int


class RunFromConfig(pydantic.BaseModel, frozen=True):
    goal_file: str
    input_file: str
    role: str


class SandboxFromConfig(pydantic.BaseModel, frozen=True):
    strategy: Strategy


class LogFromConfig(pydantic.BaseModel, frozen=True):
    socket: str = ""


class WebFromConfig(pydantic.BaseModel, frozen=True):
    allowed_domains: list[str] = []


class DocumentFromConfig(pydantic.BaseModel, frozen=True):
    workspace: WorkspaceFromConfig
    model: ModelFromConfig
    limits: LimitsFromConfig
    run: RunFromConfig
    sandbox: SandboxFromConfig
    base: str = pydantic.Field(
        default="",
        description="Absolute directory relative paths resolve against, and the import anchor "
        "for dotted module refs. Required for a document on stdin; refused in a TOML file, "
        "whose own directory is used.",
    )
    log: LogFromConfig = LogFromConfig()
    web: WebFromConfig = WebFromConfig()
    roles: dict[str, RoleFromConfig] = {}
