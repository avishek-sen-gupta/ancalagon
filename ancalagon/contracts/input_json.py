# Pulls the input out of spec.json as text, because only the caller knows what model it is.
import json


def input_json_of(spec_text: str) -> str:
    return json.dumps(json.loads(spec_text)["input"])
