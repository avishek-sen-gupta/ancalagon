# The process environment a spawned child inherits, injected so it can be curated.
import collections.abc
import typing


class Environment(typing.Protocol):
    def variables(self) -> collections.abc.Mapping[str, str]: ...
