"""Команды ядра, добавленные для бота: inspect и подпись последнего изменения в summary."""
import json

from aosr import ops
from aosr.__main__ import main


def run(capsys, *args, home="/nonexistent-home"):
    code = main(["--home", str(home), *map(str, args)])
    return code, json.loads(capsys.readouterr().out)


def test_inspect_tells_registry_from_acts(ws, acts_xlsx, pdf, tmp_path, capsys):
    assert run(capsys, "inspect", ws.registry_path) == (0, {"ok": True, "kind": "registry"})
    assert run(capsys, "inspect", acts_xlsx)[1]["kind"] == "acts"
    assert run(capsys, "inspect", pdf)[1]["kind"] == "scan"
    other = tmp_path / "note.txt"
    other.write_text("x")
    assert run(capsys, "inspect", other)[1]["kind"] == "unknown"


def test_inspect_missing_file_is_bad_file(tmp_path, capsys):
    code, out = run(capsys, "inspect", tmp_path / "нет.xlsx")
    assert code == 1 and out["error"]["code"] == "bad_file"


def test_summary_reports_last_change(ws, fake_scan, pdf):
    assert ops.summary(ws)["last_change"] is None
    ops.ingest(ws, [pdf], read_scan=fake_scan())
    ops.set_field(ws, "ЗР/ВГ/1", "place", "ПК 1+00")
    assert ops.summary(ws)["last_change"].startswith("исправлено поле place акта")


def test_literal_answer_is_taken_verbatim(ws, fake_scan, pdf):
    """Свой ответ «2» — это значение 2, а не выбор второго варианта (находка проверки №2)."""
    r = ops.ingest(ws, [pdf], read_scan=fake_scan(qty_options=["812,45", "812,48"]))
    qid = r["issues"][0]["id"]
    out = ops.resolve(ws, qid, "2", literal=True)
    assert out["value"] == "2"
    assert ops.show(ws, "ЗР/ВГ/1")["act"]["qty"] == "2"


def test_literal_flag_in_cli(ws, fake_scan, pdf, capsys):
    r = ops.ingest(ws, [pdf], read_scan=fake_scan(qty_options=["812,45", "812,48"]))
    code, out = run(capsys, "resolve", r["issues"][0]["id"], "1", "--literal", home=ws.home)
    assert code == 0 and out["value"] == "1"


def test_option_pick_still_works(ws, fake_scan, pdf):
    r = ops.ingest(ws, [pdf], read_scan=fake_scan(qty_options=["812,45", "812,48"]))
    assert ops.resolve(ws, r["issues"][0]["id"], "2")["value"] == "812,48"


def test_issue_ids_are_not_reused_after_undo(ws, fake_scan, pdf):
    """Старая кнопка не должна попасть в новый вопрос с тем же id (находка проверки №3)."""
    first = ops.ingest(ws, [pdf], read_scan=fake_scan(qty_options=["1", "2"]))["issues"][0]["id"]
    ops.undo(ws)
    second = ops.ingest(ws, [pdf], read_scan=fake_scan(qty_options=["1", "2"]))["issues"][0]["id"]
    assert first != second
