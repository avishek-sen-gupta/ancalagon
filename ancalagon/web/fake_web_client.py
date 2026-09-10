# Responses fixed at construction, so a test can say exactly what the web returned.
import collections.abc

from ancalagon.web.page import Page
from ancalagon.web.web_client import WebClient


class FakeWebClient(WebClient):
    def __init__(self, pages: collections.abc.Mapping[str, Page]):
        self.pages = dict(pages)
        self.asked: list[tuple[str, dict[str, str]]] = []

    def get(self, url: str) -> Page:
        self.asked = [*self.asked, (url, {})]
        return self.pages[url]

    def post_form(self, url: str, form: collections.abc.Mapping[str, str]) -> Page:
        self.asked = [*self.asked, (url, dict(form))]
        return self.pages[url]
