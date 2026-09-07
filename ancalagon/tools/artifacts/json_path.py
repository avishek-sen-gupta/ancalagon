# A JSON Pointer resolved into the path jq indexes with.
import pydantic


class JsonPath(pydantic.RootModel[tuple[str | int, ...]], frozen=True):
    pass


def path_of(pointer: str) -> JsonPath:
    return JsonPath(
        root=tuple(
            int(token) if token.isdecimal() else token.replace("~1", "/").replace("~0", "~")
            for token in pointer.split("/")[1:]
        )
    )
