# What a hook returns: the value to go on with, or the reason it may not.
from ancalagon.contracts.accepted import Accepted
from ancalagon.contracts.refused import Refused

Reviewed = Accepted | Refused
