# What a deterministic outcome reports: an agent with no model spends nothing.
from ancalagon.contracts.spend import Spend

NOTHING = Spend(turns=0, tool_calls=0)
