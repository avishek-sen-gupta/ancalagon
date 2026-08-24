import pathlib

import pydantic


class AstQueryArgs(pydantic.BaseModel, frozen=True):
    query: str = pydantic.Field(
        description=(
            "A tree-sitter query, as an S-expression naming captures with @, for example "
            "(function_definition name: (identifier) @fn body: (block) @body)."
        )
    )
    roots: list[pathlib.PurePath]
    language: str = pydantic.Field(description="python or java")
    globs: list[str] = pydantic.Field(
        default=[],
        description=(
            "Restrict the search to files matching these globs, for example ['*.py']. "
            "Prefix a glob with ! to exclude instead. Omit to query every file under the roots."
        ),
    )
