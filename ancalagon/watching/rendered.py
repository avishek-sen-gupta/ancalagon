# One transcript message as a terminal shows it: a header line, then each block on its own line.
from ancalagon.contracts.block import Block
from ancalagon.contracts.message import Message
from ancalagon.contracts.text import Text
from ancalagon.contracts.tool_use import ToolUse

CYAN = "[36m"
YELLOW = "[1;33m"
RED = "[31m"
OFF = "[0m"
INDENT = "  "
TEXT_WIDTHS = 4


def _flat(text: str, width: int) -> str:
    return text.replace("\n", " ")[:width]


def _block_line(block: Block, width: int) -> str:
    if isinstance(block, Text):
        return f"{INDENT}{block.text.replace('\n', f'\n{INDENT}')[: width * TEXT_WIDTHS]}\n"
    if isinstance(block, ToolUse):
        return f"{INDENT}→ {YELLOW}{block.name}{OFF} {_flat(block.arguments, width)}\n"
    marked = f"{RED}ERR{OFF} " if block.is_error else ""
    return f"{INDENT}← {marked}{_flat(block.content, width)}\n"


def rendered(label: str, message: Message, width: int) -> str:
    header = f"{CYAN}[{label}/{message.agent}]{OFF} {message.role.value[0:1].upper()}\n"
    return header + "".join(_block_line(block, width) for block in message.blocks)
