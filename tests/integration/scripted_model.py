# An OpenAI-shaped server that answers from a script, so real workers can be driven exactly.
import collections.abc
import http.server
import json
import threading

import pydantic

from ancalagon.contracts.tool_use import ToolUse
from ancalagon.llm.adapters.wire_text_block import WireTextBlock

SYSTEM = pydantic.TypeAdapter(list[WireTextBlock])

Decide = collections.abc.Callable[[str, int], list[ToolUse]]


def _body(calls: list[ToolUse]) -> bytes:
    return json.dumps(
        {
            "id": "chatcmpl-scripted",
            "object": "chat.completion",
            "created": 0,
            "model": "scripted",
            "choices": [
                {
                    "index": 0,
                    "finish_reason": "tool_calls",
                    "message": {
                        "role": "assistant",
                        "content": None,
                        "tool_calls": [
                            {
                                "id": c.id,
                                "type": "function",
                                "function": {"name": c.name, "arguments": c.arguments},
                            }
                            for c in calls
                        ],
                    },
                }
            ],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
        }
    ).encode()


class ScriptedModel:
    def __init__(self, decide: Decide):
        self.decide = decide
        self.goals: list[str] = []
        self.turns: dict[str, int] = {}
        self.requests: list[str] = []
        server = http.server.HTTPServer(("127.0.0.1", 0), self._handler())
        self.base_url = f"http://127.0.0.1:{server.server_address[1]}"
        self.server = server
        threading.Thread(target=server.serve_forever, daemon=True).start()

    def _goal_of(self, system: str) -> str:
        said = "\n".join(b.text for b in SYSTEM.validate_json(system))
        for line in said.splitlines():
            if line.startswith("Goal: "):
                return line[len("Goal: ") :]
        return ""

    def _handler(self) -> type[http.server.BaseHTTPRequestHandler]:
        outer = self

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_POST(self) -> None:
                body_text = self.rfile.read(int(self.headers["Content-Length"])).decode()
                outer.requests.append(body_text)
                asked = json.loads(body_text)
                goal = outer._goal_of(json.dumps(asked["messages"][0]["content"]))
                turn = outer.turns.get(goal, 0)
                outer.turns[goal] = turn + 1
                outer.goals.append(goal)
                out = _body(outer.decide(goal, turn))
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(out)))
                self.end_headers()
                self.wfile.write(out)

            def log_message(self, format: str, *args: str | int) -> None:
                return None

        return Handler

    def close(self) -> None:
        self.server.shutdown()
