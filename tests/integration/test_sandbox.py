# Proves the sandbox confines writes and leaves the dev toolchain working, against real fence.
import os
import pathlib
import shutil
import socket
import subprocess
import tempfile

import pytest

from ancalagon.fs.real_file_system import RealFileSystem
from ancalagon.sandbox.fence import Fence

pytestmark = pytest.mark.skipif(shutil.which("fence") is None, reason="fence is not installed")

# AF_UNIX paths are capped near 104 bytes, which pytest's tmp_path already exceeds.
SOCKET_ROOT = "/tmp"


def test_fence_confines_writes_and_leaves_the_toolchain_working(tmp_path: pathlib.Path):
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    write_root = tmp_path / "ws"
    write_root.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()

    sandbox = Fence(
        write_roots=[write_root],
        allowed_domains=[],
        run_dir=run_dir,
        fs=RealFileSystem(),
        log_socket="",
    )
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


def _listening(path: str) -> socket.socket:
    bound = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    bound.bind(path)
    bound.listen(8)
    return bound


def _line(listener: socket.socket) -> str:
    conn, _ = listener.accept()
    text = conn.recv(4096).decode()
    conn.close()
    return text


def test_a_fenced_worker_reaches_the_configured_log_socket_and_no_other(tmp_path: pathlib.Path):
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    write_root = tmp_path / "ws"
    write_root.mkdir()
    root = pathlib.Path(tempfile.mkdtemp(dir=SOCKET_ROOT))
    named, unnamed = str(root / "named.sock"), str(root / "unnamed.sock")
    allowed, refused = _listening(named), _listening(unnamed)

    sandbox = Fence(
        write_roots=[write_root],
        allowed_domains=[],
        run_dir=run_dir,
        fs=RealFileSystem(),
        log_socket=named,
    )
    env = {**os.environ, **sandbox.environment()}
    env.pop("TMPDIR", None)

    reached = subprocess.run(
        list(sandbox.wrap(["sh", "-c", f"echo configured | nc -w 1 -U {named}"])),
        capture_output=True,
        env=env,
    )
    blocked = subprocess.run(
        list(sandbox.wrap(["sh", "-c", f"echo sneaky | nc -w 1 -U {unnamed}"])),
        capture_output=True,
        env=env,
    )

    assert reached.returncode == 0
    assert _line(allowed) == "configured\n"
    assert blocked.returncode != 0
    allowed.close()
    refused.close()
