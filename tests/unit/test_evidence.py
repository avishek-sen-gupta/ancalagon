import pathlib

import pydantic
import pytest

from ancalagon.contracts.accepted import Accepted
from ancalagon.contracts.cited import Cited
from ancalagon.contracts.evidence import Evidence
from ancalagon.contracts.refused import Refused
from ancalagon.fs.real_file_system import RealFileSystem
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
            Evidence(path=cited, start_line=3, end_line=3, quote="05  INVENTED  PIC X."),
        ),
    )
    refusal = evidence_resolves(faulty, ctx)
    assert isinstance(refusal, Refused)
    assert refusal.reason.startswith("these citations do not resolve: ")
    faults = refusal.reason.removeprefix("these citations do not resolve: ").split("; ")
    assert len(faults) == 5
    assert faults[0].startswith(f"{tmp_path / 'scope' / 'gone.txt'}: not readable")
    assert faults[1].startswith(f"{tmp_path / 'elsewhere.txt'}: not readable")
    assert faults[2] == f"{cited}: lines 2-9 but the file has 3"
    assert faults[3] == f"{cited}: end_line 2 is before start_line 3"
    assert faults[4] == (
        f"{cited}: quote does not match lines 3-3, which read: 05  SECOND-FIELD   PIC X(1)."
    )

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
    assert buried.reason == (
        f"these citations do not resolve: {cited}: quote does not match lines 1-1, "
        "which read: 01  RECORD."
    )

    with pytest.raises(pydantic.ValidationError, match="path"):
        Evidence(path="scope/record.txt", start_line=1, end_line=1, quote="x")
