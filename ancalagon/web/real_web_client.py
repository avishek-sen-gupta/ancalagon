# The only place httpx is called.
import collections.abc

import httpx

from ancalagon.text.decoded import decoded
from ancalagon.web.page import Page
from ancalagon.web.unreachable import Unreachable
from ancalagon.web.web_client import WebClient

TIMEOUT_S = 30.0
MAX_BYTES = 5_000_000
AGENT = "Mozilla/5.0 (compatible; ancalagon)"


def _page(response: httpx.Response) -> Page:
    return Page(
        url=str(response.url),
        status=response.status_code,
        content_type=response.headers.get("content-type", ""),
        body=decoded(response.content[:MAX_BYTES]),
    )


class RealWebClient(WebClient):
    def get(self, url: str) -> Page:
        try:
            with httpx.Client(follow_redirects=True, timeout=TIMEOUT_S) as client:
                return _page(client.get(url, headers={"User-Agent": AGENT}))
        except httpx.HTTPError as exc:
            raise Unreachable(url, str(exc)) from exc

    def post_form(self, url: str, form: collections.abc.Mapping[str, str]) -> Page:
        try:
            with httpx.Client(follow_redirects=True, timeout=TIMEOUT_S) as client:
                return _page(client.post(url, data=dict(form), headers={"User-Agent": AGENT}))
        except httpx.HTTPError as exc:
            raise Unreachable(url, str(exc)) from exc
