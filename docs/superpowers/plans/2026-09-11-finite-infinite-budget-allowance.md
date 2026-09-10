# Finite / Infinite budget allowance

**Status:** proposed  
**Context:** hard-coded `int` budgets cannot express "no limit", which matters for
long-running investigative agents where the caller cannot predict how many turns
or tool calls are needed.

---

## Problem

`Budget` today carries `turns: int` and `tool_calls: int`. The session loop treats
both as countdown timers: decrement on each spend, fail when they reach zero.
There is no way to express "run until the agent submits an answer".

Setting large integers works as a workaround but gives misleading `spent` figures
and still terminates the agent at an arbitrary ceiling.

---

## Design

### New type: `contracts/allowance.py`

```python
Allowance = Finite | Infinite
```

```python
class Finite(pydantic.BaseModel, frozen=True):
    value: int

    def plus(self, n: int) -> "Finite":
        return Finite(value=self.value + n)

    def minus(self, n: int) -> "Finite":
        return Finite(value=self.value - n)

    def permits(self, cost: int) -> bool:
        return self.value >= cost

    def spent_since(self, start: "Allowance") -> int:
        """How many were consumed: start minus self."""
        if isinstance(start, Finite):
            return start.value - self.value
        return 0

    @property
    def exhausted(self) -> bool:
        return self.value <= 0

    def __str__(self) -> str:
        return str(self.value)


class Infinite(pydantic.BaseModel, frozen=True):

    def permits(self, cost: int) -> bool:
        return True

    def spent_since(self, start: "Allowance") -> int:
        return 0

    @property
    def exhausted(self) -> bool:
        return False

    def __str__(self) -> str:
        return "∞"
```

`plus` and `minus` exist only on `Finite` — arithmetic on `Infinite` is not
defined. Callers that spend the allowance receive `Allowance` back (unchanged for
`Infinite`, decremented for `Finite`).

---

### `contracts/budget.py`

Change both fields from `int` to `Allowance`. Add a Pydantic field validator on
each that accepts the existing `int` form and the new `"infinite"` string:

```python
@field_validator("turns", "tool_calls", mode="before")
@classmethod
def _parse(cls, v: object) -> Allowance:
    if isinstance(v, int):
        return Finite(value=v)
    if v == "infinite":
        return Infinite()
    return v  # already Allowance — pass through
```

`spend_turn`, `spend_tool_calls`, and `turns_exhausted` stay the same in shape;
they delegate to `Allowance.minus` / `Allowance.exhausted`.

---

### `session.py` — four callsites

| Before | After |
|---|---|
| `budget.turns - remaining.turns` | `remaining.turns.spent_since(budget.turns)` |
| `budget.tool_calls - remaining.tool_calls` | `remaining.tool_calls.spent_since(budget.tool_calls)` |
| `tool.cost > remaining.tool_calls` | `not remaining.tool_calls.permits(tool.cost)` |
| `f"… {remaining.tool_calls} remain"` | unchanged — `__str__` renders correctly |

---

### Config

Existing configs are unaffected — `turns = 20` is still valid and parses as
`Finite(value=20)`.

To remove the budget ceiling:

```toml
budget = { turns = "infinite", tool_calls = "infinite" }
```

Either field may be infinite independently.

---

## Files touched

| File | Change |
|---|---|
| `contracts/allowance.py` | new |
| `contracts/budget.py` | `int → Allowance`; field validator |
| `session.py` | 4 lines |
| `*.toml` configs | no change required |
