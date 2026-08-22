# Runs a worker under fence, which confines its writes and filters its network.
import collections.abc
import pathlib

import pydantic

from ancalagon.fs.file_system import FileSystem
from ancalagon.sandbox.sandbox import Sandbox

POLICY = "fence.json"


class Network(pydantic.BaseModel, frozen=True):
    allowedDomains: list[str]


class Filesystem(pydantic.BaseModel, frozen=True):
    allowWrite: list[str]


class Policy(pydantic.BaseModel, frozen=True):
    network: Network
    filesystem: Filesystem


class Fence(Sandbox):
    def __init__(
        self,
        write_root: pathlib.PurePath,
        allowed_domains: collections.abc.Sequence[str],
        run_dir: pathlib.PurePath,
        fs: FileSystem,
    ):
        self.policy = run_dir / POLICY
        fs.write_text(
            self.policy,
            Policy(
                network=Network(allowedDomains=list(allowed_domains)),
                filesystem=Filesystem(allowWrite=[str(write_root), str(run_dir)]),
            ).model_dump_json(),
        )

    def wrap(self, command: collections.abc.Sequence[str]) -> collections.abc.Sequence[str]:
        return ["fence", "-s", str(self.policy), "--", *command]

    def environment(self) -> collections.abc.Mapping[str, str]:
        return {}
