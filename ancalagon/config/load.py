# Loads a Config from a TOML file on disk.
import pathlib
import tomllib

from ancalagon.config.config import Config
from ancalagon.config.document_from_config import DocumentFromConfig
from ancalagon.config.from_document import config_from
from ancalagon.fs.file_system import FileSystem

SPLIT_WRITE_ROOT = (
    "[workspace] write_root was split into home (where runs live) and "
    "write_roots (where agents may write)"
)

TOML_STATES_NO_BASE = (
    "[base] is for a document with no file. A TOML file's own directory is its base, "
    "so remove it"
)


def load_config(path: pathlib.PurePath, fs: FileSystem) -> Config:
    document = tomllib.loads(fs.read_text(path))
    if "write_root" in document.get("workspace", {}):
        raise ValueError(SPLIT_WRITE_ROOT)
    raw = DocumentFromConfig.model_validate(document)
    if raw.base:
        raise ValueError(TOML_STATES_NO_BASE)
    return config_from(raw, fs.resolve(path).parent, fs)
