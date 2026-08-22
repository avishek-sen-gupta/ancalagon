# The only place in the codebase that reads the process environment.
import collections.abc
import os

from ancalagon.env.environment import Environment


class RealEnvironment(Environment):
    def variables(self) -> collections.abc.Mapping[str, str]:
        return dict(os.environ)
