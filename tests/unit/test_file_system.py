import os
import pathlib

from ancalagon.fs.real_file_system import RealFileSystem


def test_the_real_file_system_reads_writes_lists_and_reports_what_is_there(
    tmp_path: pathlib.Path,
):
    fs = RealFileSystem()
    nested = tmp_path / "a" / "b"

    fs.mkdir(nested, parents=True)
    assert fs.is_dir(nested) is True
    fs.mkdir(nested, parents=True, exist_ok=True)

    note = nested / "note.txt"
    assert fs.exists(note) is False
    fs.write_text(note, "hello é")
    assert fs.read_text(note) == "hello é"
    assert fs.read_bytes(note) == "hello é".encode("utf-8")

    was = fs.mtime(note)
    os.utime(note, (was + 10, was + 10))
    assert fs.mtime(note) == was + 10
    assert fs.mtime(nested / "absent.txt") == 0.0
    assert (fs.exists(note), fs.is_file(note), fs.is_dir(note)) == (True, True, False)

    fs.write_text(nested / "other.md", "x")
    assert fs.iterdir(nested) == (nested / "note.txt", nested / "other.md")
    assert fs.glob(nested, "*.md") == (nested / "other.md",)

    with fs.open_append(note) as handle:
        handle.write("\nmore")
    assert fs.read_text(note) == "hello é\nmore"

    with fs.open_write(note) as handle:
        handle.write("replaced")
    assert fs.read_text(note) == "replaced"

    assert fs.resolve(nested / ".." / "b") == nested
    assert str(fs.expanduser(pathlib.Path("~"))).startswith("/")

    fs.unlink(note)
    assert fs.exists(note) is False
