# An environment fixed at construction, so a test can say exactly what a child inherits.
import collections.abc

from ancalagon.env.environment import Environment


class FakeEnvironment(Environment):
    def __init__(self, variables: collections.abc.Mapping[str, str] = {}):
        self.given = dict(variables)

    def variables(self) -> collections.abc.Mapping[str, str]:
        return self.given
