# One end of an edge: which kind of node, and which one of them.
import pydantic

from ancalagon.trace.node_kind import NodeKind


class NodeRef(pydantic.BaseModel, frozen=True):
    kind: NodeKind
    id: int
