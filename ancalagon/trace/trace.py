# A whole run as a graph: what happened, and what caused what.
import pydantic

from ancalagon.trace.edge import Edge
from ancalagon.trace.node import Node


class Trace(pydantic.BaseModel, frozen=True):
    nodes: tuple[Node, ...]
    edges: tuple[Edge, ...]
