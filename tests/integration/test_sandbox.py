# Proves the sandbox confines writes and leaves the dev toolchain working, against real fence.
import os
import pathlib
import shutil
import subprocess

import pytest

from ancalagon.sandbox.fence import Fence

pytestmark = pytest.mark.skipif(shutil.which("fence") is None, reason="fence is not installed")


def test_fence_confines_writes_and_leaves_the_toolchain_working(tmp_path: pathlib.Path):
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    write_root = tmp_path / "ws"
    write_root.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()

    sandbox = Fence(write_root=write_root, allowed_domains=[], run_dir=run_dir)
    env = {**os.environ, **sandbox.environment()}
    env.pop("TMPDIR", None)

    allowed = subprocess.run(
        list(sandbox.wrap(["sh", "-c", f"echo ok > {write_root / 'a.txt'}"])),
        capture_output=True,
        env=env,
    )
    assert allowed.returncode == 0
    assert (write_root / "a.txt").read_text() == "ok\n"

    refused = subprocess.run(
        list(sandbox.wrap(["sh", "-c", f"echo no > {outside / 'b.txt'}"])),
        capture_output=True,
        env=env,
    )
    assert refused.returncode != 0
    assert not (outside / "b.txt").exists()

    toolchain = subprocess.run(
        list(sandbox.wrap(["rg", "--version"])), capture_output=True, text=True, env=env
    )
    assert toolchain.returncode == 0
    assert toolchain.stdout.startswith("ripgrep")
