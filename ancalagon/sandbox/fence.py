# Runs a worker under fence, which confines its writes and filters its network.
import collections.abc
import pathlib

import pydantic

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
        write_root: pathlib.Path,
        allowed_domains: collections.abc.Sequence[str],
        run_dir: pathlib.Path,
    ):
        self.policy = run_dir / POLICY
        self.policy.write_text(
            Policy(
                network=Network(allowedDomains=list(allowed_domains)),
                filesystem=Filesystem(allowWrite=[str(write_root), str(run_dir)]),
            ).model_dump_json()
        )

    def wrap(self, command: collections.abc.Sequence[str]) -> collections.abc.Sequence[str]:
        return ["fence", "-s", str(self.policy), "--", *command]

    def environment(self) -> collections.abc.Mapping[str, str]:
        return {"no_proxy": "", "NO_PROXY": ""}
