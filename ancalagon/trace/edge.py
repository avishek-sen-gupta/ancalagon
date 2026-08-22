import pydantic

from ancalagon.trace.edge_kind import EdgeKind
from ancalagon.trace.node_ref import NodeRef


class Edge(pydantic.BaseModel, frozen=True):
    kind: EdgeKind
    source: NodeRef
    target: NodeRef
    ts: str
