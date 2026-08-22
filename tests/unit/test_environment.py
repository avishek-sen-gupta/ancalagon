import pytest

from ancalagon.env.fake_environment import FakeEnvironment
from ancalagon.env.real_environment import RealEnvironment


def test_the_real_environment_reports_the_process_and_the_fake_reports_only_what_it_was_given(
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setenv("ANCALAGON_PORT_MARKER", "present")
    assert RealEnvironment().variables()["ANCALAGON_PORT_MARKER"] == "present"

    monkeypatch.delenv("ANCALAGON_PORT_MARKER")
    assert "ANCALAGON_PORT_MARKER" not in RealEnvironment().variables()

    assert FakeEnvironment({"PATH": "/bin"}).variables() == {"PATH": "/bin"}
    assert FakeEnvironment().variables() == {}
