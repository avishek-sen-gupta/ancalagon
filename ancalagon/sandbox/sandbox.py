# How a worker's command is wrapped before it is spawned, and what environment it gets.
import collections.abc
import typing


class Sandbox(typing.Protocol):
    def wrap(self, command: collections.abc.Sequence[str]) -> collections.abc.Sequence[str]: ...

    def environment(self) -> collections.abc.Mapping[str, str]: ...
