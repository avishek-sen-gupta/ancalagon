# The one place a search engine's result table becomes results.
import lxml.html

from ancalagon.tools.web.result import Result

LINKS = "//a[@class='result-link']"
SNIPPET = "ancestor::tr[1]/following-sibling::tr[1]/td[@class='result-snippet']"


def _text(element: lxml.html.HtmlElement) -> str:
    return " ".join(element.text_content().split())


def _snippet(link: lxml.html.HtmlElement) -> str:
    found = link.xpath(SNIPPET)
    return _text(found[0]) if found else ""


def results_in(html: str, count: int) -> tuple[Result, ...]:
    tree = lxml.html.fromstring(html)
    return tuple(
        Result(rank=rank, title=_text(link), url=link.get("href"), snippet=_snippet(link))
        for rank, link in enumerate(tree.xpath(LINKS)[:count], start=1)
    )
