# The tree-sitter grammars this harness can parse, named as a model refers to them.
import collections.abc

import tree_sitter
import tree_sitter_java
import tree_sitter_python

GRAMMARS: collections.abc.Mapping[str, collections.abc.Callable[[], object]] = {
    "python": tree_sitter_python.language,
    "java": tree_sitter_java.language,
}


def language_of(name: str) -> tree_sitter.Language:
    return tree_sitter.Language(GRAMMARS[name]())
