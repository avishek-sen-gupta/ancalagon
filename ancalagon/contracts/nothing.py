# The budget a deterministic outcome reports: an agent with no model spends nothing.
from ancalagon.contracts.budget import Budget

NOTHING = Budget(turns=0, tool_calls=0)
