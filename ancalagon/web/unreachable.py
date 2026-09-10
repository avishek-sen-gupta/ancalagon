# Raised when a web request never gets an answer, so httpx never leaks past the adapter.
class Unreachable(Exception):
    def __init__(self, url: str, reason: str):
        super().__init__(f"{url} is unreachable: {reason}")
