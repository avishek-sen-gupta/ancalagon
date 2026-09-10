from ancalagon.web.extracted import extracted
from ancalagon.web.fake_web_client import FakeWebClient
from ancalagon.web.page import Page

ARTICLE = """
<html><head><title>A Title</title></head><body>
<nav><ul><li><a href="/edit">Edit this page</a></li><li><a href="/talk">Talk</a></li></ul></nav>
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


def test_extraction_keeps_the_article_and_drops_the_navigation():
    text = extracted(ARTICLE)

    assert "The first paragraph explains the subject" in text
    assert "The second paragraph continues that explanation" in text
    assert "Edit this page" not in text
    assert "Copyright notice belongs to nobody." not in text


def test_extraction_of_a_page_with_no_prose_is_empty_rather_than_none():
    assert extracted("<html><body><div id='app'></div></body></html>") == ""


def test_the_fake_client_returns_scripted_pages_and_records_what_was_asked():
    page = Page(url="https://example.com/one", status=200, content_type="text/html", body="hi")
    client = FakeWebClient({"https://example.com/one": page})

    assert client.get("https://example.com/one") == page
    assert client.post_form("https://example.com/one", {"q": "a query"}) == page
    assert client.asked == [
        ("https://example.com/one", {}),
        ("https://example.com/one", {"q": "a query"}),
    ]
