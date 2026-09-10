import pathlib

import pydantic
import pytest

from ancalagon.fs.real_file_system import RealFileSystem
from ancalagon.tools.registry.bind_tool import bind_tool
from ancalagon.tools.registry.tool_context import ToolContext
from ancalagon.tools.web.fetch_args import FetchArgs
from ancalagon.tools.web.fetch_url import FetchUrl
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


PAGE = """
<html><head><title>A Title</title></head><body>
<nav><ul><li><a href="/edit">Edit this page</a></li></ul></nav>
<article>
<h1>A Title</h1>
<p>The first paragraph explains the subject at enough length that an extractor treats it as the
main content of the page rather than as boilerplate around the edges of it.</p>
<p>The second paragraph continues that explanation, so the article carries more prose than the
navigation does, which is the signal the extractor decides on.</p>
</article>
<footer>Copyright notice belongs to nobody.</footer>
</body></html>
"""

TARGET = "https://example.com/article"


def _serving(body: str, status: int = 200, content_type: str = "text/html") -> FakeWebClient:
    return FakeWebClient(
        {TARGET: Page(url=TARGET, status=status, content_type=content_type, body=body)}
    )


def test_fetch_writes_the_article_text_without_the_navigation(tmp_path: pathlib.Path):
    ctx = _ctx(tmp_path)
    client = _serving(PAGE)

    got = FetchUrl(client).run(FetchArgs(url=TARGET), ctx)

    assert got.ok is True
    assert client.asked == [(TARGET, {})]
    written = pathlib.Path(got.path).read_text()
    assert "The first paragraph explains the subject" in written
    assert "The second paragraph continues that explanation" in written
    assert "Edit this page" not in written
    assert "Copyright notice belongs to nobody." not in written
    assert got.byte_count == len(written.encode("utf-8"))


def test_fetch_fails_naming_the_url_status_and_type_when_nothing_can_be_extracted(
    tmp_path: pathlib.Path,
):
    client = _serving("%PDF-1.4 binary rubbish", content_type="application/pdf")

    got = FetchUrl(client).run(FetchArgs(url=TARGET), _ctx(tmp_path))

    assert got.ok is False
    assert got.error == f"extracted no text from {TARGET} (200, application/pdf)"


def test_fetch_reports_a_bad_status_as_a_failure(tmp_path: pathlib.Path):
    got = FetchUrl(_serving("", status=404)).run(FetchArgs(url=TARGET), _ctx(tmp_path))

    assert got.ok is False
    assert got.error == f"{TARGET} answered 404"


def test_a_non_https_url_is_refused_by_the_schema_not_by_the_tool(tmp_path: pathlib.Path):
    with pytest.raises(pydantic.ValidationError):
        FetchArgs(url="http://example.com/article")

    bound = bind_tool(FetchUrl(_serving(PAGE)))
    with pytest.raises(pydantic.ValidationError, match="url"):
        bound.invoke('{"url": "ftp://example.com/article"}', _ctx(tmp_path))
