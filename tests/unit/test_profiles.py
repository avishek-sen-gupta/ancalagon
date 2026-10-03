import collections.abc
import pathlib

import pytest

from ancalagon.bus.no_bus import NO_BUS
from ancalagon.contracts.budget import Budget
from ancalagon.contracts.class_ref import ClassRef
from ancalagon.contracts.delivery import Delivery
from ancalagon.contracts.finite import Finite
from ancalagon.contracts.free_text import FreeText
from ancalagon.contracts.function_ref import FunctionRef
from ancalagon.contracts.idling import Idling
from ancalagon.contracts.no_answer_file import NO_ANSWER_FILE
from ancalagon.contracts.no_watermark import NO_WATERMARK
from ancalagon.contracts.pending import PENDING
from ancalagon.contracts.serialisable_role import SerialisableRole
from ancalagon.contracts.spend import Spend
from ancalagon.fs.real_file_system import RealFileSystem
from ancalagon.llm.inlined import Inlined
from ancalagon.profiles.answering import ANSWERING, TURNS_GONE, Answering
from ancalagon.profiles.answering_as_file import ANSWERING_AS_FILE, AnsweringAsFile
from ancalagon.profiles.answering_as_file import ANSWER_FILE
from ancalagon.profiles.catalogue import Catalogue
from ancalagon.profiles.deterministic import DETERMINISTIC, Deterministic
from ancalagon.profiles.profile import Profile
from ancalagon.profiles.resolve_profile import resolve_profile
from ancalagon.profiles.standing import MECHANICS, STANDING, Standing
from ancalagon.profiles.turn import Turn
from ancalagon.tools.delegate.collect_task import CollectTask
from ancalagon.tools.idle.idle import Idle
from ancalagon.tools.idle.no_idle import NoIdle
from ancalagon.tools.registry.bind_tool import bind_tool
from ancalagon.tools.registry.bound_tool import BoundTool
from ancalagon.contracts.no_tool import NO_TOOL
from ancalagon.tools.search.ripgrep import Ripgrep
from ancalagon.tools.submit.submit_answer import SubmitAnswer
from ancalagon.tools.submit.submit_answer_as_file import SubmitAnswerAsFile
from ancalagon.profiles.answering import ANSWERING
from tests.unit.conftest import written_budget

WORKING = (
    bind_tool(Ripgrep()),
    bind_tool(NoIdle()),
    bind_tool(CollectTask(NO_BUS, RealFileSystem())),
)

SUBMITS = bind_tool(SubmitAnswer(FreeText))

SUBMITS_FILE = bind_tool(SubmitAnswerAsFile(FreeText))

# available_tools builds both submit tools; assemble offers a role only the one it uses.
CATALOGUE = Catalogue((*WORKING, SUBMITS, SUBMITS_FILE))

OFFERED = (*WORKING, SUBMITS)

OFFERED_FILE = (*WORKING, SUBMITS_FILE)


ROLE = SerialisableRole(
    profile=ANSWERING,
    behaviour="Look.",
    answer=ClassRef(module="ancalagon.contracts.free_text", name="FreeText"),
    tools=("ripgrep",),
    budget=written_budget(3, 9),
)


def _turn(
    turns: int = 3,
    offered: tuple[BoundTool, ...] = OFFERED,
    outstanding: tuple[int, ...] = (),
    uncollected: tuple[int, ...] = (),
    tries: int = 2,
    delivered: Delivery = Delivery.NOTHING,
) -> Turn:
    return Turn(
        output_class=FreeText,
        offered=offered,
        remaining=Budget(turns=Finite(value=turns), tool_calls=Finite(value=9)),
        spent=Spend(turns=1, tool_calls=2),
        outstanding=outstanding,
        uncollected=uncollected,
        tries=tries,
        delivered=delivered,
    )


def _names(tools: collections.abc.Sequence[BoundTool]) -> list[str]:
    return sorted(tool.spec.declaration.name for tool in tools)


def _brought(profile: Profile) -> list[str]:
    return sorted(spec.declaration.name for spec in profile.tools)


def _forced(profile: Profile, turn: Turn) -> str:
    forced = profile.forces(turn)
    assert isinstance(forced, BoundTool)
    return forced.spec.declaration.name


def test_an_answering_profile_withholds_idle_and_submit_until_it_is_time_for_each(
    tmp_path: pathlib.Path,
):
    profile = Answering(CATALOGUE)

    assert _brought(profile) == sorted(Answering.brings()) == ["idle", "submit_answer"]

    alone = _turn()
    assert profile.halts(alone) is PENDING
    assert _names(profile.offers(alone)) == ["collect_task", "ripgrep", "submit_answer"]

    waiting = _turn(outstanding=(4,))
    assert _names(profile.offers(waiting)) == ["collect_task", "idle", "ripgrep"]

    owed = _turn(uncollected=(4,))
    assert _names(profile.offers(owed)) == ["collect_task", "ripgrep"]

    final_owed = _turn(turns=0, uncollected=(4,))
    assert profile.halts(final_owed) is PENDING
    assert _names(profile.offers(final_owed)) == ["collect_task"]
    assert _forced(profile, final_owed) == "collect_task"
    assert "these children have answers you have never read: [4]" in profile.instructs(final_owed)

    final_done = _turn(turns=0, uncollected=(4,), tries=0)
    assert _forced(profile, final_done) == "submit_answer"
    assert _names(profile.offers(final_done)) == ["submit_answer"]
    assert profile.instructs(final_done) == (
        "Your budget is exhausted. Answer now from what you already know, "
        "using the submit_answer tool. No other tools are available."
    )

    final_waiting = _turn(turns=0, outstanding=(4,))
    assert profile.halts(final_waiting) == Idling(
        summary=TURNS_GONE, spent=Spend(turns=1, tool_calls=2), seen_through=NO_WATERMARK
    )

    assert profile.nudges(alone) == (
        "Answers are only accepted through the submit_answer tool. Keep working, and "
        "call it when you have your answer."
    )
    assert profile.nudges(_turn(delivered=Delivery.NOTE)) == (
        "Noted. Carry on, and call the submit_answer tool when you have your answer."
    )
    assert profile.mechanics(alone) == (
        "When you have the answer, call the submit_answer tool with it. That tool is "
        "the only way to answer; a reply without it is taken as more work to do. "
        "Your answer must match this schema: "
        f"{FreeText.model_json_schema(schema_generator=Inlined)}"
    )


def test_answering_as_a_file_changes_only_which_tool_ends_the_run(tmp_path: pathlib.Path):
    profile = AnsweringAsFile(CATALOGUE)

    assert profile.terminal.declaration.name == "submit_answer_as_file"
    assert (
        _brought(profile) == sorted(AnsweringAsFile.brings()) == ["idle", "submit_answer_as_file"]
    )

    final = _turn(turns=0, offered=OFFERED_FILE)
    assert _forced(profile, final) == "submit_answer_as_file"
    assert _names(profile.offers(final)) == ["submit_answer_as_file"]

    alone = _turn(offered=OFFERED_FILE)
    assert _names(profile.offers(alone)) == [
        "collect_task",
        "ripgrep",
        "submit_answer_as_file",
    ]

    waiting = _turn(offered=OFFERED_FILE, outstanding=(4,))
    assert _names(profile.offers(waiting)) == ["collect_task", "idle", "ripgrep"]
    assert "submit_answer_as_file tool" in profile.nudges(waiting)


def test_a_profile_that_overrides_nothing_never_answers_and_withholds_nothing(
    tmp_path: pathlib.Path,
):
    class Bare(Profile):
        pass

    profile = Bare(CATALOGUE)
    turn = _turn(turns=0, outstanding=(4,), uncollected=(5,))

    assert profile.tools == ()
    assert profile.halts(turn) is PENDING
    assert profile.forces(turn) is NO_TOOL
    assert profile.offers(turn) == OFFERED
    assert profile.mechanics(turn) == ""
    assert profile.instructs(turn) == ""
    assert profile.nudges(turn) == ""
    assert profile.faults("investigator", ROLE) == ""


def test_a_profile_is_resolved_by_reference_and_anything_else_is_refused():
    assert resolve_profile(ANSWERING) is Answering

    with pytest.raises(TypeError, match="FreeText in ancalagon.contracts.free_text"):
        resolve_profile(ClassRef(module="ancalagon.contracts.free_text", name="FreeText"))


def test_a_catalogue_finds_a_tool_by_either_class_that_could_have_filled_its_slot():
    assert CATALOGUE.spec_for(Idle, NoIdle).declaration.name == "idle"
    assert CATALOGUE.spec_for(NoIdle).source is NoIdle
    assert CATALOGUE.spec_for(SubmitAnswer).declaration.name == "submit_answer"

    with pytest.raises(LookupError, match="this agent has no Idle"):
        CATALOGUE.spec_for(Idle)


RUN = FunctionRef(module="ancalagon.watch.watch_for", name="watch_for")

FREE_TEXT_REF = ClassRef(module="ancalagon.contracts.free_text", name="FreeText")


def _role(**changes: ClassRef | FunctionRef) -> SerialisableRole:
    base = SerialisableRole(
        profile=ANSWERING,
        behaviour="Look.",
        tools=("ripgrep",),
        budget=written_budget(3, 9),
    )
    return base.model_copy(update=changes)


def test_each_profile_refuses_a_role_that_does_not_fit_the_kind_of_agent_it_is():
    assert Answering.faults("scout", _role()) == ""
    assert Answering.faults("scout", _role(run=RUN)) == (
        "[roles.scout] is Answering but names run watch_for in ancalagon.watch.watch_for; "
        "a role that runs a function holds no session to answer in"
    )
    assert Answering.faults("stray", _role(answer_file=FREE_TEXT_REF)) == (
        "[roles.stray] declares answer_file as FreeText in ancalagon.contracts.free_text, "
        "but Answering answers with the value itself, so nothing checks it"
    )

    filing = _role(profile=ANSWERING_AS_FILE, answer=ANSWER_FILE, answer_file=FREE_TEXT_REF)
    assert AnsweringAsFile.faults("filer", filing) == ""
    assert AnsweringAsFile.faults(
        "filer", filing.model_copy(update={"answer_file": NO_ANSWER_FILE})
    ) == (
        "[roles.filer] is AnsweringAsFile, so it must declare answer_file: "
        "the class its answer file holds"
    )
    assert AnsweringAsFile.faults("filer", filing.model_copy(update={"answer": FREE_TEXT_REF})) == (
        "[roles.filer] declares answer as FreeText in ancalagon.contracts.free_text, but "
        "AnsweringAsFile answers with AnswerFile in ancalagon.contracts.answer_file"
    )
    assert AnsweringAsFile.faults("filer", filing.model_copy(update={"run": RUN})) == (
        "[roles.filer] is AnsweringAsFile but names run watch_for in ancalagon.watch.watch_for; "
        "a role that runs a function holds no session to answer in"
    )

    assert Deterministic.faults("ticker", _role(profile=DETERMINISTIC)) == (
        "[roles.ticker] is Deterministic, so it must name a run function"
    )
    watching = _role(
        profile=DETERMINISTIC,
        run=RUN,
        input=ClassRef(module="ancalagon.contracts.watch_request", name="WatchRequest"),
        answer=ClassRef(module="ancalagon.contracts.watched", name="Watched"),
    )
    assert Deterministic.faults("watcher", watching) == ""
    assert Deterministic.faults(
        "watcher", watching.model_copy(update={"answer": FREE_TEXT_REF})
    ) == (
        "[roles.watcher] declares answer as FreeText in ancalagon.contracts.free_text, but its "
        "run function watch_for in ancalagon.watch.watch_for states answer as Watched in "
        "ancalagon.contracts.watched"
    )


def test_a_standing_profile_never_answers_and_withholds_nothing(tmp_path: pathlib.Path):
    profile = Standing(CATALOGUE)

    assert _brought(profile) == sorted(Standing.brings()) == ["idle"]

    waiting = _turn(outstanding=(4,))
    assert profile.halts(waiting) is PENDING
    assert profile.forces(waiting) is NO_TOOL
    assert profile.offers(waiting) == OFFERED
    assert profile.instructs(waiting) == ""
    assert profile.nudges(waiting) == ""
    assert profile.mechanics(waiting) == MECHANICS

    # A standing agent is not released from the loop by running out of turns with children live.
    final = _turn(turns=0, outstanding=(4,))
    assert profile.halts(final) is PENDING
    assert profile.offers(final) == OFFERED

    assert Standing.faults("watcher", _role(profile=STANDING)) == ""
    assert Standing.faults("watcher", _role(profile=STANDING, run=RUN)) == (
        "[roles.watcher] is Standing but names run watch_for in ancalagon.watch.watch_for; "
        "a role that runs a function holds no session to answer in"
    )
    answering = _role(
        profile=STANDING,
        answer=ClassRef(module="ancalagon.contracts.watched", name="Watched"),
    )
    assert Standing.faults("watcher", answering) == (
        "[roles.watcher] declares answer as Watched in ancalagon.contracts.watched, but "
        "Standing never answers, so nothing would submit it"
    )
    assert Standing.faults("watcher", _role(profile=STANDING, answer_file=FREE_TEXT_REF)) == (
        "[roles.watcher] declares answer_file as FreeText in ancalagon.contracts.free_text, "
        "but Standing never answers, so nothing would check it"
    )
