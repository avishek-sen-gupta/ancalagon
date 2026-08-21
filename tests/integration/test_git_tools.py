# The git-backed tools, exercised against a real repository.
import pathlib

import pydantic
import pytest

from ancalagon.tools.history.git_history import GitHistory
from ancalagon.tools.history.git_operation import GitOperation
from ancalagon.tools.history.history_args import HistoryArgs
from ancalagon.tools.registry.tool_context import ToolContext
from ancalagon.tools.search.ast_grep import AstGrep
from ancalagon.tools.search.find_symbol import FindSymbol
from ancalagon.tools.search.grep_args import GrepArgs
from ancalagon.tools.search.ripgrep import Ripgrep
from ancalagon.tools.search.run_command import run_command
from ancalagon.tools.search.symbol_args import SymbolArgs
from ancalagon.tools.survey.code_stats import CodeStats
from ancalagon.tools.survey.stats_args import StatsArgs
from ancalagon.workspace.workspace import Workspace


def _ctx(tmp_path: pathlib.Path) -> ToolContext:
    write_root = tmp_path / "ws"
    write_root.mkdir(exist_ok=True)
    outputs = write_root / "outputs"
    outputs.mkdir(exist_ok=True)
    return ToolContext(
        workspace=Workspace(write_root=write_root, read_roots=(write_root,)),
        output_dir=outputs,
        summary_chars=50,
        agent_id=17,
    )


def test_git_history_reports_intent_and_refuses_option_injection(tmp_path: pathlib.Path):
    ctx = _ctx(tmp_path)
    repo = ctx.workspace.write_root
    tracked = repo / "thing.py"
    tracked.write_text("x = 1\n")
    for command in (
        ["git", "init", "-q"],
        ["git", "config", "user.email", "t@example.com"],
        ["git", "config", "user.name", "T"],
        ["git", "add", "thing.py"],
        ["git", "commit", "-q", "-m", "workaround for a vendor bug"],
    ):
        run_command(["git", "-C", str(repo), *command[1:]])

    log = GitHistory().run(HistoryArgs(path=tracked, operation=GitOperation.LOG), ctx)
    assert log.ok is True
    assert "workaround for a vendor bug" in log.path.read_text()

    blame = GitHistory().run(HistoryArgs(path=tracked, operation=GitOperation.BLAME), ctx)
    assert blame.ok is True
    assert "x = 1" in blame.path.read_text()

    with pytest.raises(pydantic.ValidationError):
        HistoryArgs(path=tracked, operation=GitOperation.SHOW, rev="--upload-pack=x")

    missing = GitHistory().run(HistoryArgs(path=tracked, operation=GitOperation.SHOW), ctx)
    assert missing.ok is False
    assert "needs a rev" in missing.error


def test_tree_walking_tools_all_honour_gitignore(tmp_path: pathlib.Path):
    ctx = _ctx(tmp_path)
    root = ctx.workspace.write_root
    (root / "src").mkdir()
    (root / "vendored").mkdir()
    (root / ".gitignore").write_text("vendored/\n")
    run_command(["git", "-C", str(root), "init", "-q"])
    (root / "src" / "real.py").write_text("def real_thing(): pass\n")
    (root / "vendored" / "dep.py").write_text("def vendored_thing(): pass\n")

    symbols = FindSymbol().run(SymbolArgs(roots=[root]), ctx).path.read_text()
    assert "real_thing" in symbols
    assert "vendored_thing" not in symbols

    matches = Ripgrep().run(GrepArgs(pattern="thing", roots=[root]), ctx).path.read_text()
    assert "real.py" in matches
    assert "dep.py" not in matches

    counted = CodeStats().run(StatsArgs(roots=[root], by_file=True), ctx).path.read_text()
    assert "real.py" in counted
    assert "dep.py" not in counted

    structural = (
        AstGrep().run(GrepArgs(pattern="def $N(): pass", roots=[root]), ctx).path.read_text()
    )
    assert "real.py" in structural
    assert "dep.py" not in structural
