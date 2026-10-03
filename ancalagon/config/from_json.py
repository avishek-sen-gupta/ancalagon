# A Config from a JSON document with no file behind it, and the stdin it can arrive on.
import pathlib
import typing

from ancalagon.config.config import Config
from ancalagon.config.document_from_config import DocumentFromConfig
from ancalagon.config.from_document import config_from
from ancalagon.fs.file_system import FileSystem

JSON_STATES_ITS_BASE = (
    "a document with no file states its base: the absolute directory its relative paths "
    "resolve against, and the import anchor for its dotted module refs"
)

BASE_IS_ABSOLUTE = (
    "base is {base}, which is relative. A document read from stdin has no location to "
    "resolve it against, so it must be absolute"
)

BASE_IS_A_DIRECTORY = "base names {base}, which is not a directory"

STDIN_IS_A_TERMINAL = (
    "--config-json reads the document from stdin, and stdin is a terminal: "
    "pipe the document in, or use --config with a TOML file"
)


def _stated_base(raw: DocumentFromConfig) -> str:
    if not raw.base:
        raise ValueError(JSON_STATES_ITS_BASE)
    return raw.base


def _resolvable_base(base: pathlib.PurePath, fs: FileSystem) -> pathlib.PurePath:
    if not base.is_absolute():
        raise ValueError(BASE_IS_ABSOLUTE.format(base=base))
    if not fs.is_dir(base):
        raise ValueError(BASE_IS_A_DIRECTORY.format(base=base))
    return base


def config_from_json(document: str, fs: FileSystem) -> Config:
    raw = DocumentFromConfig.model_validate_json(document)
    base = fs.expanduser(pathlib.PurePath(_stated_base(raw)))
    return config_from(raw, fs.resolve(_resolvable_base(base, fs)), fs)


class Stdin(typing.Protocol):
    def isatty(self) -> bool: ...

    def read(self) -> str: ...


def document_on_stdin(stdin: Stdin) -> str:
    if stdin.isatty():
        raise ValueError(STDIN_IS_A_TERMINAL)
    return stdin.read()
