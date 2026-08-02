import json


def input_json_of(spec_text: str) -> str:
    return json.dumps(json.loads(spec_text)["input"])
