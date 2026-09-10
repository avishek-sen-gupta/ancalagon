# Every HTTP request the harness makes, so that making one is an injected dependency.
import collections.abc
import typing

from ancalagon.web.page import Page


class WebClient(typing.Protocol):
    def get(self, url: str) -> Page: ...

    def post_form(self, url: str, form: collections.abc.Mapping[str, str]) -> Page: ...
