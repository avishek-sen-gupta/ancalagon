# Imports the profile class a role names, and refuses anything that is not one.
import importlib

from ancalagon.contracts.class_ref import ClassRef
from ancalagon.profiles.profile import Profile


def resolve_profile(ref: ClassRef) -> type[Profile]:
    resolved = getattr(importlib.import_module(ref.module), ref.name)
    if not (isinstance(resolved, type) and issubclass(resolved, Profile)):
        raise TypeError(f"{ref.name} in {ref.module} is not a profile")
    return resolved
