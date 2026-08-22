import pathlib

from ancalagon.bus.bus_meter import BusMeter
from ancalagon.bus.connect import connect
from ancalagon.bus.lifecycle_store import LifecycleStore
from ancalagon.bus.meter_store import MeterStore
from ancalagon.clock.system_clock import SystemClock
from ancalagon.contracts.call_usage import CallUsage
from ancalagon.fs.real_file_system import RealFileSystem
from ancalagon.llm.meter import Meter
from ancalagon.llm.unmetered import Unmetered
from ancalagon.migrations import latest_version, migrate_file
from ancalagon.schedule.task_of import task_of


def test_calls_accumulate_per_agent_and_survive_across_agents(tmp_path: pathlib.Path):
    migrate_file(tmp_path / "bus.db", latest_version(RealFileSystem()), RealFileSystem())
    conn = connect(tmp_path / "bus.db", RealFileSystem())
    clock = SystemClock()
    bus = LifecycleStore(conn, clock)
    meter_store = MeterStore(conn, clock)
    first = bus.enqueue(tmp_path / "tasks" / "alpha", parent_agent=0)
    second = bus.enqueue(tmp_path / "tasks" / "beta", parent_agent=first)
    meter: Meter = BusMeter(meter_store)

    meter.record(first, CallUsage(model="m", prompt_tokens=100, completion_tokens=10))
    meter.record(
        first,
        CallUsage(model="m", prompt_tokens=200, completion_tokens=20, cache_read_tokens=90),
    )
    meter.record(second, CallUsage(model="m", prompt_tokens=7, completion_tokens=1))

    assert [c.prompt_tokens for c in meter_store.calls(first)] == [100, 200]
    assert meter_store.calls(second)[0].completion_tokens == 1

    totals = meter_store.tokens_by_agent()
    assert totals[first].prompt_tokens == 300
    assert totals[first].completion_tokens == 30
    assert totals[first].cache_read_tokens == 90
    assert totals[second].prompt_tokens == 7

    retried = bus.enqueue(tmp_path / "tasks" / "alpha", parent_agent=0)
    meter.record(retried, CallUsage(model="m", prompt_tokens=5))
    snapshot = bus.snapshot()
    assert task_of(snapshot, retried).id == task_of(snapshot, first).id
    assert sorted(totals | meter_store.tokens_by_agent()) == [first, second, retried]

    run_total = sum(u.prompt_tokens for u in meter_store.tokens_by_agent().values())
    assert run_total == 312


def test_the_no_op_meter_records_nothing_and_satisfies_the_protocol(tmp_path: pathlib.Path):
    quiet: Meter = Unmetered()
    quiet.record(1, CallUsage(prompt_tokens=999))

    migrate_file(tmp_path / "bus.db", latest_version(RealFileSystem()), RealFileSystem())

    conn = connect(tmp_path / "bus.db", RealFileSystem())
    clock = SystemClock()
    bus = LifecycleStore(conn, clock)
    meter_store = MeterStore(conn, clock)
    agent = bus.enqueue(tmp_path / "tasks" / "a", parent_agent=0)
    assert meter_store.calls(agent) == []
    assert meter_store.tokens_by_agent() == {}
