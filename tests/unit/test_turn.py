import pathlib

import pydantic

from ancalagon.contracts.budget import Budget
from ancalagon.contracts.delivery import Delivery
from ancalagon.contracts.finite import Finite
from ancalagon.contracts.free_text import FreeText
from ancalagon.contracts.infinite import Infinite
from ancalagon.contracts.spend import Spend
from ancalagon.profiles.turn import Turn
from ancalagon.tools.registry.bind_tool import bind_tool
from ancalagon.tools.registry.no_tool import NO_TOOL
from ancalagon.tools.registry.registry import Registry
from ancalagon.tools.search.ripgrep import Ripgrep
from ancalagon.tools.submit.submit_answer import SubmitAnswer


def _turn(tmp_path: pathlib.Path, budget: Budget, tries: int = 2) -> Turn:
    registry = Registry([bind_tool(Ripgrep()), bind_tool(SubmitAnswer(FreeText))])
    return Turn(
        output_class=FreeText,
        offered=registry.bound(),
        remaining=budget,
        spent=Spend(turns=0, tool_calls=0),
        outstanding=(),
        uncollected=(4,),
        tries=tries,
        delivered=Delivery.NOTE,
    )


def test_a_turn_derives_finality_and_finds_a_bound_tool_by_its_spec(tmp_path: pathlib.Path):
    turn = _turn(tmp_path, Budget(turns=Finite(value=2), tool_calls=Finite(value=9)))

    assert turn.final is False
    assert turn.uncollected == (4,)
    assert turn.delivered is Delivery.NOTE
    assert sorted(t.spec.declaration.name for t in turn.offered) == ["ripgrep", "submit_answer"]

    grep = next(t for t in turn.offered if t.spec.declaration.name == "ripgrep")
    assert turn.bound(grep.spec) is grep

    assert [t.spec.source for t in turn.offered] == [Ripgrep, SubmitAnswer]
    by_class = {t.spec.source: t for t in turn.offered}
    assert turn.bound(by_class[SubmitAnswer].spec) is by_class[SubmitAnswer]

    unheld = bind_tool(SubmitAnswer(pydantic.create_model("Other", answer=(str, ...)))).spec
    assert turn.bound(unheld) is NO_TOOL

    assert _turn(tmp_path, Budget(turns=Finite(value=0), tool_calls=Finite(value=9))).final is True
    assert _turn(tmp_path, Budget(turns=Infinite(), tool_calls=Finite(value=9))).final is False
