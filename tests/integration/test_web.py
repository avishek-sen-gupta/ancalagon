import os
import pathlib

import pytest

from ancalagon.fs.real_file_system import RealFileSystem
from ancalagon.tools.registry.tool_context import ToolContext
from ancalagon.tools.web.fetch_args import FetchArgs
from ancalagon.tools.web.fetch_url import FetchUrl
from ancalagon.tools.web.search_args import SearchArgs
from ancalagon.tools.web.web_search import WebSearch
from ancalagon.web.real_web_client import RealWebClient
from ancalagon.workspace.workspace import Workspace

pytestmark = pytest.mark.skipif(
    os.environ.get("ANCALAGON_WEB") != "1",
    reason="reaches the live web; set ANCALAGON_WEB=1 to run",
)


def _ctx(tmp_path: pathlib.Path) -> ToolContext:
    write_root = tmp_path / "ws"
    write_root.mkdir(exist_ok=True)
    return ToolContext(
        workspace=Workspace(RealFileSystem(), write_root=write_root, read_roots=(write_root,)),
        task_dir=write_root,
        summary_chars=1000,
        agent_id=1,
    )


def test_a_search_and_a_fetch_against_the_live_web(tmp_path: pathlib.Path):
    ctx = _ctx(tmp_path)
    client = RealWebClient()

    found = WebSearch(client).run(SearchArgs(query="pydantic model_validate_json", count=5), ctx)
    assert found.ok is True
    urls = [
        line
        for line in pathlib.Path(found.path).read_text().splitlines()
        if line.startswith("https://")
    ]
    assert len(urls) == 5

    got = FetchUrl(client).run(FetchArgs(url="https://docs.python.org/3/library/json.html"), ctx)
    assert got.ok is True
    assert "json (javascript object notation)" in pathlib.Path(got.path).read_text().lower()
