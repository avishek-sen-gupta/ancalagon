# What one agent was assembled with: the tools it may call, and the policy deciding when.
import dataclasses

from ancalagon.profiles.profile import Profile
from ancalagon.tools.registry.registry import Registry


@dataclasses.dataclass(frozen=True)
class Assembly:
    registry: Registry
    profile: Profile
