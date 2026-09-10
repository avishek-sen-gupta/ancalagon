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


def _hrefed(link: lxml.html.HtmlElement) -> tuple[tuple[lxml.html.HtmlElement, str], ...]:
    match link.get("href"):
        case str() as href:
            return ((link, href),)
        case _:
            return ()


def results_in(html: str, count: int) -> tuple[Result, ...]:
    tree = lxml.html.fromstring(html)
    linked = tuple(pair for link in tree.xpath(LINKS) for pair in _hrefed(link))[:count]
    return tuple(
        Result(rank=rank, title=_text(link), url=href, snippet=_snippet(link))
        for rank, (link, href) in enumerate(linked, start=1)
    )
