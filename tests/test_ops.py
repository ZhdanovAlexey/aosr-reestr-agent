import openpyxl

from aosr.ops import delete, export, find, ingest, restore, set_field, show, summary, undo
from aosr.registry import C_NUM, FIRST_ROW
from conftest import code_of, edit_book


def write_cell(registry_path, number, col, value):
    """Правка «руками в Excel»: записать значение в строку акта с данным номером."""
    wb = openpyxl.load_workbook(registry_path)
    ws = wb["общий"]
    for r in range(FIRST_ROW, ws.max_row + 1):
        if ws.cell(r, C_NUM).value == number:
            ws.cell(r, col).value = value
            break
    else:
        raise AssertionError(f"нет акта {number}")
    wb.save(registry_path)


def test_ingest_example_book(ws, acts_xlsx):
    r = ingest(ws, [acts_xlsx])
    assert (len(r["added"]), r["updated"], r["total"], r["errors"]) == (12, [], 12, [])
    assert len(r["notes"]) == 3
    dates = [a["date"] for a in find(ws)["acts"]]
    assert dates == sorted(dates) and dates[0] == "2024-07-09"
    assert r["registry"] == str(ws.registry_path) and r["open_issues"] == 0


def test_reingest_updates_without_duplicates(ws, acts_xlsx):
    ingest(ws, [acts_xlsx])
    r = ingest(ws, [acts_xlsx])
    assert (r["added"], len(r["updated"]), r["total"]) == ([], 12, 12)


def test_manual_fix_survives_reingest(ws, acts_xlsx):
    ingest(ws, [acts_xlsx])
    r = set_field(ws, "ВО/11-15/БО", "place", "колодцы 11-15")
    assert (r["old"], r["new"]) == ("11-15", "колодцы 11-15")
    ingest(ws, [acts_xlsx])
    assert show(ws, "ВО/11-15/БО")["act"]["place"] == "колодцы 11-15"


def test_manual_columns_survive(ws, acts_xlsx):
    ingest(ws, [acts_xlsx])
    write_cell(ws.registry_path, number="ВО/11-15/РГ", col=15, value="Реестр 7")
    ingest(ws, [acts_xlsx])
    assert show(ws, "ВО/11-15/РГ")["act"]["manual"] == {"O": "Реестр 7"}


def test_example_from_spec(ws, acts_xlsx):
    ingest(ws, [acts_xlsx])
    a = show(ws, "ВО/21-31/МТ")["act"]
    assert (a["code"], a["unit"], a["qty"], a["date"]) == ("5.3.1.31\n5.3.1.32", "м\nшт", "87,5\n10", "2025-02-18")
    assert a["place"] == "ДК21 - 7, ДК23 - 8, ДК25 - 9"
    assert len(a["appendices"]) == 7 and a["issues"] == []


def test_delete_and_undo(ws, acts_xlsx):
    ingest(ws, [acts_xlsx])
    r = delete(ws, "ВО/11-15/БО")
    assert r["removed_rows"] == 7 and summary(ws)["total"] == 11
    assert undo(ws)["undone"].startswith("удалён акт") and summary(ws)["total"] == 12


def test_deleted_act_does_not_return_on_reingest(ws, acts_xlsx):
    ingest(ws, [acts_xlsx])
    delete(ws, "ВО/11-15/БО")
    r = ingest(ws, [acts_xlsx])
    assert r["total"] == 11 and any("удалён ранее" in n["text"] for n in r["notes"])
    restore(ws, "ВО/11-15/БО")
    assert ingest(ws, [acts_xlsx])["added"] == ["ВО/11-15/БО"]


def test_unknown_and_ambiguous_number(ws, acts_xlsx):
    ingest(ws, [acts_xlsx])
    assert code_of(lambda: show(ws, "НЕТ/0")) == "act_not_found"
    assert code_of(lambda: show(ws, "ВО/11-15")) == "ambiguous_number"
    assert code_of(lambda: delete(ws, "НЕТ/0")) == "act_not_found"
    assert summary(ws)["total"] == 12
    assert show(ws, "во/11-15/бо")["act"]["number"] == "ВО/11-15/БО"      # регистр и пробелы не важны


def test_duplicate_number_in_one_upload(ws, tmp_path, acts_xlsx):
    book = edit_book(acts_xlsx, tmp_path / "dup.xlsx", lambda wb: wb.copy_worksheet(wb.worksheets[0]))
    r = ingest(ws, [book])
    assert r["total"] == 12 and any("дважды" in n["text"] for n in r["notes"])


def test_bad_file_does_not_block_others(ws, tmp_path, acts_xlsx, template_xlsx):
    junk = tmp_path / "x.docx"
    junk.write_text("?")
    r = ingest(ws, [junk, template_xlsx, acts_xlsx])
    assert [e["code"] for e in r["errors"]] == ["bad_file", "bad_file"] and r["total"] == 12
    assert "реестр" in r["errors"][1]["message"]


def test_only_bad_files_leave_registry_untouched(ws, tmp_path):
    junk = tmp_path / "x.xlsx"
    junk.write_text("не архив")
    before = ws.registry_path.read_bytes()
    r = ingest(ws, [junk])
    assert r["errors"][0]["code"] == "bad_file" and ws.registry_path.read_bytes() == before and ws.history() == []


def test_set_validation(ws, acts_xlsx):
    ingest(ws, [acts_xlsx])
    assert code_of(lambda: set_field(ws, "ВО/11-15/БО", "color", "x")) == "bad_field"
    assert code_of(lambda: set_field(ws, "ВО/11-15/БО", "date", "вчера")) == "bad_value"
    assert code_of(lambda: set_field(ws, "ВО/11-15/БО", "appendix.99", "x")) == "bad_value"
    assert code_of(lambda: set_field(ws, "ВО/11-15/БО", "number", "ВО/11-15/РГ")) == "bad_value"   # номер занят
    assert set_field(ws, "ВО/11-15/БО", "date", "20.07.2024")["new"] == "20.07.2024г."


def test_set_appendix_and_number(ws, acts_xlsx):
    ingest(ws, [acts_xlsx])
    n = len(show(ws, "ВО/11-15/БО")["act"]["appendices"])
    set_field(ws, "ВО/11-15/БО", "appendix.1", "Схема - 3 листа;")
    set_field(ws, "ВО/11-15/БО", f"appendix.{n + 1}", "Доп. протокол - 1 лист;")
    set_field(ws, "ВО/11-15/БО", "number", "ВО/11-15/БО-испр")
    ingest(ws, [acts_xlsx])                                   # правки, включая номер, переживают повторную загрузку
    a = show(ws, "ВО/11-15/БО-испр")["act"]
    assert a["appendices"][0] == "Схема - 3 листа;" and a["appendices"][-1] == "Доп. протокол - 1 лист;" and len(a["appendices"]) == n + 1
    assert summary(ws)["total"] == 12


def test_find(ws, acts_xlsx):
    ingest(ws, [acts_xlsx])
    aug = find(ws, date_from="2024-08-01", date_to="2024-08-31")
    assert aug["count"] == len(aug["acts"]) > 0 and all(a["date"].startswith("2024-08") for a in aug["acts"])
    assert find(ws, number="21-31/МТ")["acts"][0]["number"] == "ВО/21-31/МТ"
    backfill = find(ws, text="обратная засыпка")                 # модель ищет в именительном падеже
    assert backfill["count"] == 3 and all("ОЗ" in a["number"] for a in backfill["acts"])
    assert find(ws, text="несуществующее слово")["count"] == 0
    assert code_of(lambda: find(ws, date_from="август")) == "bad_value"
    assert set(aug["acts"][0]) == {"number", "date", "work", "place", "appendices", "open_issues"}


def test_summary_and_export(ws, acts_xlsx):
    ingest(ws, [acts_xlsx])
    assert summary(ws) == {"total": 12, "date_from": "2024-07-09", "date_to": "2025-09-04", "open_issues": 0, "history": 1,
                           "last_change": "загрузка: файлов 1, добавлено 12, обновлено 0"}
    assert export(ws) == {"registry": str(ws.registry_path), "open_issues": 0, "issues_by_act": {}}
