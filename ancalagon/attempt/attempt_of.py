# Folds an attempt's events into the single state they describe.
import functools
from collections.abc import Sequence

from ancalagon.attempt.attempt import Attempt
from ancalagon.attempt.nascent import Nascent
from ancalagon.attempt.next_state import next_state
from ancalagon.contracts.agent_event import AgentEvent


def attempt_of(events: Sequence[AgentEvent]) -> Attempt:
    return functools.reduce(next_state, events, Nascent())
