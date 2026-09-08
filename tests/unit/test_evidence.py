import pathlib

import pydantic
import pytest

from ancalagon.clock.fake_clock import FakeClock
from ancalagon.contracts.accepted import Accepted
from ancalagon.contracts.cited import Cited
from ancalagon.contracts.evidence import Evidence
from ancalagon.contracts.refused import Refused
from ancalagon.fs.real_file_system import RealFileSystem
from ancalagon.tools.files.read_args import ReadArgs
from ancalagon.tools.files.read_file import ReadFile
from ancalagon.tools.registry.tool_context import ToolContext
from ancalagon.tools.submit.evidence_resolves import evidence_resolves
from ancalagon.workspace.workspace import Workspace

SOURCE = """       01  RECORD.
           05  FIRST-FIELD    PIC X(01).
           05  SECOND-FIELD   PIC X(1).
"""


class Finding(Cited, frozen=True):
    claim: str
    evidence: tuple[Evidence, ...]

    def citations(self) -> tuple[Evidence, ...]:
        return self.evidence


class Report(Cited, frozen=True):
    findings: tuple[Finding, ...]
    evidence: tuple[Evidence, ...]

    def citations(self) -> tuple[Evidence, ...]:
        return self.evidence + tuple(c for f in self.findings for c in f.citations())


def _ctx(tmp_path: pathlib.Path) -> ToolContext:
    scope = tmp_path / "scope"
    scope.mkdir()
    (scope / "record.txt").write_text(SOURCE)
    workspace = Workspace(
        RealFileSystem(), write_root=tmp_path / "ws", read_roots=(scope, tmp_path / "ws")
    )
    workspace.mkdir(tmp_path / "ws", parents=True, exist_ok=True)
    return ToolContext(workspace, tmp_path / "ws" / "task", summary_chars=400, agent_id=1)


def test_a_citation_is_accepted_only_when_it_quotes_the_lines_it_names(tmp_path: pathlib.Path):
    ctx = _ctx(tmp_path)
    cited = str(tmp_path / "scope" / "record.txt")

    quoted = Finding(
        claim="the field is one byte",
        evidence=(
            Evidence(
                path=cited,
                start_line=2,
                end_line=2,
                quote="           05  FIRST-FIELD    PIC X(01).",
            ),
        ),
    )
    assert evidence_resolves(quoted, ctx) == Accepted(value=quoted)

    faulty = Finding(
        claim="everything at once",
        evidence=(
            Evidence(
                path=str(tmp_path / "scope" / "gone.txt"), start_line=1, end_line=1, quote="x"
            ),
            Evidence(path=str(tmp_path / "elsewhere.txt"), start_line=1, end_line=1, quote="x"),
            Evidence(path=cited, start_line=2, end_line=9, quote="x"),
            Evidence(path=cited, start_line=3, end_line=2, quote="x"),
            Evidence(
                path=cited,
                start_line=2,
                end_line=3,
                quote="05  FIRST-FIELD    PIC X(01).\n05  INVENTED  PIC X.",
            ),
        ),
    )
    refusal = evidence_resolves(faulty, ctx)
    assert isinstance(refusal, Refused)
    reported = refusal.reason.splitlines()
    assert reported[0] == "these citations do not resolve:"
    assert reported[1].startswith(f"{tmp_path / 'scope' / 'gone.txt'}: not readable")
    assert reported[2].startswith(f"{tmp_path / 'elsewhere.txt'}: not readable")
    assert reported[3] == f"{cited}: lines 2-9 but the file has 3"
    assert reported[4] == f"{cited}: end_line 2 is before start_line 3"
    assert reported[5:] == [
        f"{cited}: quote does not match lines 2-3. Rows are = same, - only in your quote, "
        "+ only in the file, numbered quote:file.",
        "= 1:2 05  FIRST-FIELD    PIC X(01).",
        "- 2:- 05  INVENTED  PIC X.",
        "+ -:3 05  SECOND-FIELD   PIC X(1).",
    ]

    nested = Report(
        findings=(
            Finding(
                claim="wrong",
                evidence=(Evidence(path=cited, start_line=1, end_line=1, quote="not line one"),),
            ),
        ),
        evidence=(Evidence(path=cited, start_line=1, end_line=1, quote="01  RECORD."),),
    )
    buried = evidence_resolves(nested, ctx)
    assert isinstance(buried, Refused)
    assert buried.reason == "\n".join(
        (
            "these citations do not resolve:",
            f"{cited}: quote does not match lines 1-1. Rows are = same, - only in your quote, "
            "+ only in the file, numbered quote:file.",
            "- 1:- not line one",
            "+ -:1 01  RECORD.",
        )
    )

    with pytest.raises(pydantic.ValidationError, match="path"):
        Evidence(path="scope/record.txt", start_line=1, end_line=1, quote="x")


def test_the_numbers_read_file_prints_are_the_numbers_a_citation_may_name(tmp_path: pathlib.Path):
    ctx = _ctx(tmp_path)
    cited = tmp_path / "scope" / "record.txt"

    shown = ReadFile(FakeClock()).run(ReadArgs(path=cited, offset=1, limit=1), ctx)
    body, note = shown.summary.text_for_model().splitlines()
    assert note == "[lines 2-2 of 3; call again with offset=2 for more]"
    number, quote = body.split("\t", 1)
    assert (number, quote) == ("2", "           05  FIRST-FIELD    PIC X(01).")

    copied = Finding(
        claim="the numbers came from the tool, not from counting",
        evidence=(
            Evidence(path=str(cited), start_line=int(number), end_line=int(number), quote=quote),
        ),
    )
    assert evidence_resolves(copied, ctx) == Accepted(value=copied)
