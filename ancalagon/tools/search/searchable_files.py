# The files ripgrep would search: the one definition of scope every search tool shares.
import collections.abc
from ancalagon.tools.search.run_command import run_command

# A file list is passed to some tools as arguments, and the OS caps their total size.
ARG_BUDGET = 200_000


def searchable_files(roots: collections.abc.Sequence[str]) -> tuple[int, list[str], str]:
    code, out, err = run_command(["rg", "--files", "--no-require-git", *roots])
    return code, out.splitlines(), err


def fits_in_arguments(files: collections.abc.Sequence[str]) -> bool:
    return sum(len(f) + 1 for f in files) < ARG_BUDGET
