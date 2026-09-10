import pathlib

from ancalagon.fs.real_file_system import RealFileSystem
from ancalagon.tools.registry.tool_context import ToolContext
from ancalagon.tools.web.search_args import SearchArgs
from ancalagon.tools.web.web_search import ENDPOINT, WebSearch
from ancalagon.web.fake_web_client import FakeWebClient
from ancalagon.web.page import Page
from ancalagon.workspace.workspace import Workspace

DDG_PAGE = """
<html><body><table>
<tr><td valign="top">1.&nbsp;</td>
    <td><a rel="nofollow" href="https://example.com/one" class='result-link'>First Result</a></td>
</tr>
<tr><td>&nbsp;</td><td class='result-snippet'>The first snippet.</td></tr>
<tr><td valign="top">2.&nbsp;</td>
    <td><a rel="nofollow" href="https://example.org/two" class='result-link'>Second Result</a></td>
</tr>
<tr><td>&nbsp;</td><td class='result-snippet'>The second <b>snippet</b>.</td></tr>
</table></body></html>
"""


def _ctx(tmp_path: pathlib.Path) -> ToolContext:
    write_root = tmp_path / "ws"
    write_root.mkdir(exist_ok=True)
    return ToolContext(
        workspace=Workspace(RealFileSystem(), write_root=write_root, read_roots=(write_root,)),
        task_dir=write_root,
        summary_chars=50,
        agent_id=17,
    )


def _answered(body: str, status: int = 200) -> FakeWebClient:
    return FakeWebClient(
        {ENDPOINT: Page(url=ENDPOINT, status=status, content_type="text/html", body=body)}
    )


def test_search_writes_ranked_results_to_the_task_directory(tmp_path: pathlib.Path):
    ctx = _ctx(tmp_path)
    client = _answered(DDG_PAGE)

    found = WebSearch(client).run(SearchArgs(query="a query"), ctx)

    assert found.ok is True
    assert client.asked == [(ENDPOINT, {"q": "a query"})]
    assert pathlib.Path(found.path).read_text() == (
        "1. First Result\n"
        "https://example.com/one\n"
        "The first snippet.\n"
        "\n"
        "2. Second Result\n"
        "https://example.org/two\n"
        "The second snippet."
    )
    assert found.summary.text_for_model() == "1. First Result\nhttps://example.com/one\nThe first "
    assert found.truncated is True


def test_search_honours_the_count_it_was_given(tmp_path: pathlib.Path):
    found = WebSearch(_answered(DDG_PAGE)).run(SearchArgs(query="a query", count=1), _ctx(tmp_path))

    assert pathlib.Path(found.path).read_text() == (
        "1. First Result\nhttps://example.com/one\nThe first snippet."
    )


def test_search_reports_a_bad_status_as_a_failure_naming_it(tmp_path: pathlib.Path):
    found = WebSearch(_answered("", status=503)).run(SearchArgs(query="a query"), _ctx(tmp_path))

    assert found.ok is False
    assert found.error == f"{ENDPOINT} answered 503 for 'a query'"


def test_search_reports_an_empty_result_table_as_a_failure(tmp_path: pathlib.Path):
    empty = "<html><body><table></table></body></html>"
    found = WebSearch(_answered(empty)).run(SearchArgs(query="a query"), _ctx(tmp_path))

    assert found.ok is False
    assert found.error == "no results for 'a query'"
