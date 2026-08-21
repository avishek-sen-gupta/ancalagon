# Every task whose parent agent should be woken because a child has news.
from ancalagon.attempt.snapshot import Snapshot
from ancalagon.contracts.harness_task import HarnessTask
from ancalagon.schedule.has_news import has_news


def wakeable(snapshot: Snapshot) -> tuple[HarnessTask, ...]:
    return tuple(t for t in snapshot.tasks if has_news(snapshot, t.id))
