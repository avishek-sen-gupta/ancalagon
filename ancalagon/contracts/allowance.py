# What a budget's field holds: a fixed amount, or no limit at all.
from ancalagon.contracts.finite import Finite
from ancalagon.contracts.infinite import Infinite

Allowance = Finite | Infinite
