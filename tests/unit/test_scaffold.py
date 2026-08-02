import pathlib

import ancalagon


def test_package_imports_and_migrations_are_present():
    root = pathlib.Path(ancalagon.__file__).parent
    assert (root / "migrations" / "001_init.up.sql").exists()
    assert (root / "migrations" / "001_init.down.sql").exists()
