import pathlib

from ancalagon.fs.real_file_system import RealFileSystem
from ancalagon.letterbox.file_letterbox import NOTES, FileLetterbox
from ancalagon.letterbox.no_letterbox import NO_LETTERBOX


def _leave(task_dir: pathlib.PurePath, stamp: str, text: str) -> None:
    fs = RealFileSystem()
    fs.mkdir(task_dir / NOTES, parents=True, exist_ok=True)
    fs.write_text(task_dir / NOTES / f"{stamp}.txt", text)


def test_notes_are_read_oldest_first_and_marking_consumes_only_what_was_delivered(
    tmp_path: pathlib.Path,
):
    task_dir = pathlib.PurePath(tmp_path)
    box = FileLetterbox(RealFileSystem(), task_dir)

    assert box.unread() == ()

    _leave(task_dir, "20260908T110000000000", "stop guessing the shape")
    _leave(task_dir, "20260908T110500000000", "read the definition first")
    assert box.unread() == ("stop guessing the shape", "read the definition first")

    _leave(task_dir, "20260908T111000000000", "arrived during the drain")
    box.mark(2)

    assert box.unread() == ("arrived during the drain",)
    box.mark(1)
    assert box.unread() == ()
    assert RealFileSystem().glob(task_dir / NOTES, "*.txt") == ()


def test_a_session_without_a_letterbox_never_has_a_note():
    assert NO_LETTERBOX.unread() == ()
    NO_LETTERBOX.mark(0)
