# A tool call once the registry has said which tool it names. Never written to a transcript:
# a loaded one knows only the name, because the tools on offer can differ between attempts.
import dataclasses

from ancalagon.tools.registry.bound_tool import BoundTool


@dataclasses.dataclass(frozen=True)
class ToolUse:
    id: str
    tool: BoundTool
    arguments: str
