import pytest

from aosr.errors import AosrError
from aosr.ops import find, ingest, issues, resolve, show
from aosr.scan import read_scan


def test_read_scan_returns_primary_act_and_questions(scan_pdf, chat_from_fixtures):
    act, qs, notes = read_scan(scan_pdf, chat=chat_from_fixtures)
    assert act.number == "ЗР/ВГ/1" and act.items[1].code == "3.2.1.4" and act.origin == "scan"
    assert "code" in [q["field"] for q in qs] and notes == []


def test_one_model_down(scan_pdf, chat_failing_for):
    act, qs, notes = read_scan(scan_pdf, chat=chat_failing_for("qwen3.8-27b-noreason"))
    assert act.number == "ЗР/ВГ/1" and qs == []
    assert notes == ["проверено одной моделью: qwen3.8-27b-noreason недоступна"]


def test_primary_down_falls_back_to_secondary(scan_pdf, chat_failing_for):
    act, qs, notes = read_scan(scan_pdf, chat=chat_failing_for("qwen3.6-fp8-noreason"))
    assert act.items[1].code == "3.2.1.5" and qs == [] and "qwen3.6-fp8-noreason" in notes[0]


def test_both_models_down(scan_pdf, chat_failing_for):
    with pytest.raises(AosrError) as e:
        read_scan(scan_pdf, chat=chat_failing_for("qwen3.6-fp8-noreason", "qwen3.8-27b-noreason"))
    assert e.value.code == "model_error"


def test_scan_ingest_end_to_end(ws, scan_pdf, acts_xlsx, chat_from_fixtures):
    ingest(ws, [acts_xlsx])
    r = ingest(ws, [scan_pdf], read_scan=lambda p: read_scan(p, chat=chat_from_fixtures))
    assert r["added"] == ["ЗР/ВГ/1"] and r["total"] == 13 and r["errors"] == []
    assert any("из скана" in n["text"] for n in r["notes"])
    assert r["open_issues"] == len(r["issues"]) > 0
    assert find(ws, date_from="2024-08-13", date_to="2024-08-13")["acts"][0]["number"] == "ЗР/ВГ/1"
    code_q = next(q for q in r["issues"] if q["field"] == "code")
    resolve(ws, code_q["id"], "2")                                     # человек выбрал прочтение второй модели
    assert show(ws, "ЗР/ВГ/1")["act"]["code"].split("\n")[1] == "3.2.1.5"


def test_model_error_for_one_file_keeps_others(ws, scan_pdf, acts_xlsx, chat_failing_for):
    down = chat_failing_for("qwen3.6-fp8-noreason", "qwen3.8-27b-noreason")
    r = ingest(ws, [scan_pdf, acts_xlsx], read_scan=lambda p: read_scan(p, chat=down))
    assert [e["code"] for e in r["errors"]] == ["model_error"] and r["total"] == 12


def test_answered_question_does_not_return(ws, scan_pdf, chat_from_fixtures):
    scan = lambda p: read_scan(p, chat=chat_from_fixtures)
    for q in ingest(ws, [scan_pdf], read_scan=scan)["issues"]:
        resolve(ws, q["id"], "1")
    assert ingest(ws, [scan_pdf], read_scan=scan)["issues"] == [] and issues(ws)["open"] == 0
