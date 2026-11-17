import pytest

from aosr.errors import AosrError
from aosr.store import Workspace
from conftest import code_of


def _issue(st, number="ВО/1"):
    return st.new_issue(number=number, kind="mismatch", field="qty", options=["1", "2"], fragments=["1", "2"])


def test_init_creates_registry_once(ws, small_template):
    assert ws.registry_path.exists() and ws.inbox.is_dir()
    assert code_of(lambda: ws.init(small_template)) == "already_initialized"


def test_undo_restores_registry_and_state(ws):
    before = ws.registry_path.read_bytes()
    ws.snapshot("добавлены акты")
    ws.registry_path.write_bytes(b"changed")
    st = ws.load_state()
    _issue(st)
    st.overrides["ВО/1"] = {"place": "11-15"}
    ws.save_state(st)
    assert ws.undo() == "добавлены акты"
    assert ws.registry_path.read_bytes() == before
    st = ws.load_state()
    assert st.issues == [] and st.overrides == {}


def test_undo_without_history(ws):
    assert code_of(ws.undo) == "nothing_to_undo"


def test_undo_goes_back_step_by_step(ws):
    ws.snapshot("первое"); ws.registry_path.write_bytes(b"one")
    ws.snapshot("второе"); ws.registry_path.write_bytes(b"two")
    assert ws.undo() == "второе" and ws.registry_path.read_bytes() == b"one"
    assert ws.undo() == "первое" and ws.history() == []


def test_history_is_capped(ws):
    for i in range(55):
        ws.snapshot(f"шаг {i}")
    assert len(ws.history()) == 50 and ws.history()[-1] == "шаг 54" and ws.history()[0] == "шаг 5"


def test_state_roundtrip_and_sequential_ids(ws):
    st = ws.load_state()
    a = _issue(st, "x")
    st.pending[a.id] = {"number": "x"}
    ws.save_state(st)
    st = ws.load_state()
    b = _issue(st, "y")
    assert (a.id, b.id) == ("q1", "q2")
    assert st.issues[0].options == ["1", "2"] and st.issues[0].status == "open" and st.pending == {"q1": {"number": "x"}}


def test_commands_require_registry(tmp_path):
    assert code_of(Workspace(tmp_path / "nope").require) == "no_registry"
