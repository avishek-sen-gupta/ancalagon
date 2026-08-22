# The three kinds of node a trace holds, discriminated on kind.
from ancalagon.trace.agent_node import AgentNode
from ancalagon.trace.task_node import TaskNode
from ancalagon.trace.tool_call_node import ToolCallNode

Node = TaskNode | AgentNode | ToolCallNode
