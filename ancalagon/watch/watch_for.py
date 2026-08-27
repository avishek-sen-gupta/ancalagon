# Waits for a file to change, then ends. The whole of a watcher.
import pathlib

from ancalagon.contracts.watch_request import WatchRequest
from ancalagon.contracts.watched import Watched
from ancalagon.deterministic.run_context import RunContext


def watch_for(request: WatchRequest, ctx: RunContext) -> Watched:
    watched = pathlib.PurePath(request.path)
    while ctx.fs.changed_at(watched) <= request.since:
        ctx.clock.sleep(request.poll_s)
    return Watched(path=request.path, at=ctx.fs.changed_at(watched))
