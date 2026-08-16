# The strategy that sandboxes nothing, so an unsandboxed run is a choice rather than a branch.
import collections.abc

from ancalagon.sandbox.sandbox import Sandbox


class Unsandboxed(Sandbox):
    def wrap(self, command: collections.abc.Sequence[str]) -> collections.abc.Sequence[str]:
        return command

    def environment(self) -> collections.abc.Mapping[str, str]:
        return {}
