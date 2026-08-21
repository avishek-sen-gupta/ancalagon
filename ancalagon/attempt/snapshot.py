# Everything about a run's lifecycle state, read once and folded once.
from collections.abc import Mapping

import pydantic

from ancalagon.attempt.attempt import Attempt
from ancalagon.contracts.agent_event import AgentEvent
from ancalagon.contracts.harness_task import HarnessTask


class Snapshot(pydantic.BaseModel, frozen=True):
    tasks: tuple[HarnessTask, ...]
    agents_by_task: Mapping[int, tuple[int, ...]]
    task_by_agent: Mapping[int, int]
    events: Mapping[int, tuple[AgentEvent, ...]]
    attempts: Mapping[int, Attempt]
