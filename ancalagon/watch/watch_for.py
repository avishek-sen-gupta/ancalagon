# Waits for a file to change, then ends. The whole of a watcher.
import pathlib

from ancalagon.contracts.completed import Completed
from ancalagon.contracts.function_ref import FunctionRef
from ancalagon.contracts.nothing import NOTHING
from ancalagon.contracts.outcome import Outcome
from ancalagon.contracts.watch_request import WatchRequest
from ancalagon.contracts.watched import Watched
from ancalagon.deterministic.run_context import RunContext

WATCH_FOR = FunctionRef(module="ancalagon.watch.watch_for", name="watch_for")


def watch_for(request: WatchRequest, ctx: RunContext) -> Outcome[Watched]:
    watched = pathlib.PurePath(request.path)
    while ctx.fs.changed_at(watched) <= request.since:
        ctx.clock.sleep(request.poll_s)
    at = ctx.fs.changed_at(watched)
    return Completed(
        value=Watched(path=request.path, at=at),
        summary=f"{request.path} changed at {at}",
        spent=NOTHING,
    )
