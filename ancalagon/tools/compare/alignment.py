# Two ranges of lines laid side by side, each row saying which line it is on each side.
import collections.abc
import difflib

import pydantic

MATCH = "="
ONLY_LEFT = "-"
ONLY_RIGHT = "+"
ABSENT = "-"
EQUAL = "equal"

Opcode = tuple[str, int, int, int, int]


class Alignment(pydantic.BaseModel, frozen=True):
    rows: tuple[str, ...]
    matching: int
    only_left: int
    only_right: int


def _row(marker: str, left: str, right: str, text: str) -> str:
    return f"{marker} {left}:{right} {text}"


def _rows(
    opcode: Opcode,
    left_lines: collections.abc.Sequence[str],
    right_lines: collections.abc.Sequence[str],
    left_start: int,
    right_start: int,
) -> list[str]:
    tag, i1, i2, j1, j2 = opcode
    if tag == EQUAL:
        return [
            _row(MATCH, str(left_start + i), str(right_start + j), left_lines[i])
            for i, j in zip(range(i1, i2), range(j1, j2), strict=True)
        ]
    return [_row(ONLY_LEFT, str(left_start + i), ABSENT, left_lines[i]) for i in range(i1, i2)] + [
        _row(ONLY_RIGHT, ABSENT, str(right_start + j), right_lines[j]) for j in range(j1, j2)
    ]


def align(
    left_lines: collections.abc.Sequence[str],
    right_lines: collections.abc.Sequence[str],
    left_start: int,
    right_start: int,
) -> Alignment:
    left_text = [line.rstrip() for line in left_lines]
    right_text = [line.rstrip() for line in right_lines]
    opcodes: collections.abc.Sequence[Opcode] = difflib.SequenceMatcher(
        a=left_text, b=right_text
    ).get_opcodes()
    return Alignment(
        rows=tuple(
            row
            for opcode in opcodes
            for row in _rows(opcode, left_text, right_text, left_start, right_start)
        ),
        matching=sum(i2 - i1 for tag, i1, i2, *_ in opcodes if tag == EQUAL),
        only_left=sum(i2 - i1 for tag, i1, i2, *_ in opcodes if tag != EQUAL),
        only_right=sum(j2 - j1 for tag, _i1, _i2, j1, j2 in opcodes if tag != EQUAL),
    )
