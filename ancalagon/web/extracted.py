# The one place a page's HTML becomes the article's text.
import trafilatura


def extracted(html: str) -> str:
    return trafilatura.extract(html, include_links=False) or ""
