"""Тесты на находки итоговой проверки (каждый сначала падал)."""
import json
from datetime import date, datetime

import openpyxl
import pytest

from aosr import __main__ as cli
from aosr.errors import AosrError
from aosr.llm import chat_json
from aosr.model import WorkItem, parse_item
from aosr.ops import delete, ingest, issues, replace_registry, resolve, set_field, show, summary
from aosr.registry import FIRST_ROW, Block, act_cells, init_registry, load, save, sort_blocks
from conftest import code_of
from test_ops import write_cell


# C1: настоящая дата Excel в ячейке
def test_excel_date_cells_become_text(tmp_path, small_template, make_act):
    out = tmp_path / "r.xlsx"
    init_registry(small_template, out)
    save(out, [Block(cells=act_cells(make_act("ВО/1", date(2024, 7, 11))), tail=[])], out)
    wb = openpyxl.load_workbook(out)
    wb["общий"].cell(FIRST_ROW, 7).value = datetime(2025, 2, 20)      # человек ввёл дату в Excel
    wb["общий"].cell(FIRST_ROW, 12).value = datetime(2024, 7, 22)
    wb.save(out)
    b = load(out)[0]
    assert (b.cells[7], b.cells[12], b.date) == ("20.02.2025г.", "22.07.2024", date(2025, 2, 20))
    save(out, load(out), out)
    assert load(out)[0].cells[7] == "20.02.2025г."


def test_date_typed_in_excel_survives_replace_and_reingest(ws, acts_xlsx, tmp_path):
    ingest(ws, [acts_xlsx])
    theirs = tmp_path / "m.xlsx"
    theirs.write_bytes(ws.registry_path.read_bytes())
    write_cell(theirs, number="ВО/11-15/БО", col=7, value=datetime(2024, 7, 20))
    replace_registry(ws, theirs, missing="keep")
    ingest(ws, [acts_xlsx])
    assert show(ws, "ВО/11-15/БО")["act"]["date"] == "2024-07-20"


# I1: чужой документ с тем же номером
def test_foreign_document_with_same_number_is_not_overwritten(ws, pdf, fake_scan):
    foreign = Block(cells={5: "Журнал бетонных работ", 8: "ЗР/ВГ/1", 14: "ООО «Ромашка»"}, tail=[{6: "Том 1"}])
    save(ws.registry_path, [foreign], ws.registry_path)
    r = ingest(ws, [pdf], read_scan=fake_scan())
    assert (r["added"], r["updated"], r["total"]) == (["ЗР/ВГ/1"], [], 1)
    kept = [b for b in load(ws.registry_path) if b.cells.get(5) == "Журнал бетонных работ"]
    assert kept and kept[0].cells == foreign.cells and kept[0].tail == foreign.tail
    assert summary(ws)["total"] == 1


# I2: изменяющие команды — только по точному номеру
def test_mutating_commands_need_exact_number(ws, acts_xlsx):
    ingest(ws, [acts_xlsx])
    assert show(ws, "21-31/МТ")["act"]["number"] == "ВО/21-31/МТ"          # чтение — можно по части
    assert code_of(lambda: delete(ws, "21-31/МТ")) == "act_not_found"
    assert code_of(lambda: set_field(ws, "21-31/МТ", "qty", "1")) == "act_not_found"
    assert summary(ws)["total"] == 12


# I3: диапазон размеров не количество
@pytest.mark.parametrize("line", ["Устройство основания из щебня фр. 20-40 мм", "Труба d-110 мм", "Слой толщиной 10-15 см"])
def test_size_range_is_not_quantity(line):
    item, ok = parse_item(line)
    assert not ok and item.name == line and item.qty == ""


# I4: неожиданный ответ хаба и внутренняя ошибка
@pytest.mark.parametrize("data", [{"choices": [{"message": None}]}, {"choices": []}, "не словарь"])
def test_malformed_hub_reply_is_model_error(monkeypatch, data):
    monkeypatch.setenv("NEURALDEEP_API_KEY", "k")
    with pytest.raises(AosrError) as e:
        chat_json("m", "p", [], transport=lambda *a: data)
    assert e.value.code == "model_error"


def test_non_json_body_is_model_error(monkeypatch):
    monkeypatch.setenv("NEURALDEEP_API_KEY", "k")
    def transport(*a):
        raise json.JSONDecodeError("bad", "<html>", 0)
    with pytest.raises(AosrError) as e:
        chat_json("m", "p", [], transport=transport)
    assert e.value.code == "model_error"


def test_unexpected_exception_in_one_file_keeps_others(ws, pdf, acts_xlsx):
    def boom(path):
        raise RuntimeError("что-то сломалось")
    r = ingest(ws, [pdf, acts_xlsx], read_scan=boom)
    assert [e["code"] for e in r["errors"]] == ["internal_error"] and r["total"] == 12


def test_cli_prints_json_on_internal_error(monkeypatch, capsys, tmp_path):
    monkeypatch.setattr(cli, "dispatch", lambda ws, a: (_ for _ in ()).throw(RuntimeError("бум")))
    assert cli.main(["--home", str(tmp_path), "summary"]) == 1
    out = json.loads(capsys.readouterr().out)
    assert out["ok"] is False and out["error"]["code"] == "internal_error" and "бум" in out["error"]["message"]


# I5: коды стоят напротив своих работ
def test_codes_stay_aligned_with_works(make_act):
    a = make_act("X", date(2025, 1, 1), items=[WorkItem("", "Доп. работа", "1", "м3"), WorkItem("2.1", "Работа", "2", "м3")])
    assert act_cells(a)[4] == "\n2.1" and act_cells(a)[6] == "Доп. работа\nРабота"
    b = make_act("X", date(2025, 1, 1), items=[WorkItem("", "Доп. работа", "1", "м3")])
    assert 4 not in act_cells(b)


# I6: заметки правее колонки P едут вместе со своей строкой
def test_notes_beyond_column_p_move_with_their_act(ws, pdf, fake_scan, tmp_path, make_act):
    later = Block(cells={**act_cells(make_act("ВО/9", date(2025, 1, 1))), 17: "заметка инженера"}, tail=[])
    save(ws.registry_path, [later], ws.registry_path)
    ingest(ws, [pdf], read_scan=fake_scan())                              # акт от 13.08.2024 встаёт выше
    blocks = load(ws.registry_path)
    assert [b.key for b in blocks] == ["ЗР/ВГ/1", "ВО/9"] and blocks[1].cells[17] == "заметка инженера"
    assert 17 not in blocks[0].cells


def test_init_clears_template_leftovers_beyond_p(tmp_path, template_xlsx):
    out = tmp_path / "r.xlsx"
    init_registry(template_xlsx, out)
    sheet = openpyxl.load_workbook(out)["общий"]
    foot = next(r for r in range(FIRST_ROW, sheet.max_row + 1) if str(sheet.cell(r, 1).value or "").startswith("Сдал"))
    assert not [c.coordinate for row in sheet.iter_rows(min_row=FIRST_ROW, max_row=foot - 1, min_col=17) for c in row if c.value is not None]


# M1: отвеченный вопрос по составу работ не возвращается
def test_answered_items_question_does_not_return(ws, pdf):
    from aosr.model import Act
    opts = [{"code": "2.1", "work": "А\nБ", "unit": "м3\nм3", "qty": "1\n2"}, {"code": "2.1", "work": "А", "unit": "м3", "qty": "1"}]
    def scan(path):
        act = Act(number="ЗР/ВГ/1", date=date(2024, 8, 13), title="t", origin="scan",
                  items=[WorkItem("2.1", "А", "1", "м3"), WorkItem("", "Б", "2", "м3")], appendices=["Схема"])
        return act, [{"kind": "mismatch", "field": "items", "options": opts, "fragments": ["2 строки работ", "1 строка работ"]}], []
    q = ingest(ws, [pdf], read_scan=scan)["issues"][0]["id"]
    resolve(ws, q, "2")
    assert ingest(ws, [pdf], read_scan=scan)["issues"] == [] and issues(ws)["open"] == 0
    assert show(ws, "ЗР/ВГ/1")["act"]["work"] == "А"
