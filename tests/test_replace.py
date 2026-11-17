import shutil

import openpyxl

from aosr.ops import ingest, replace_registry, set_field, show, summary
from aosr.registry import load, save
from conftest import code_of, edit_book
from test_ops import write_cell


def _copy_without(ws, tmp_path, number):
    """Копия реестра, «скачанная инженером», без одного акта."""
    path = tmp_path / "from_engineer.xlsx"
    shutil.copy(ws.registry_path, path)
    save(path, [b for b in load(path) if b.cells.get(8) != number], path)
    return path


def test_check_reports_lost_acts_without_changes(ws, acts_xlsx, tmp_path):
    ingest(ws, [acts_xlsx])
    theirs = _copy_without(ws, tmp_path, "ВО/11-15/РГ")
    r = replace_registry(ws, theirs)
    assert r == {"missing": ["ВО/11-15/РГ"], "incoming_total": 11} and summary(ws)["total"] == 12


def test_keep_adds_lost_acts_back(ws, acts_xlsx, tmp_path):
    ingest(ws, [acts_xlsx])
    theirs = _copy_without(ws, tmp_path, "ВО/11-15/РГ")
    write_cell(theirs, number="ВО/11-15/БО", col=15, value="Реестр 7")
    r = replace_registry(ws, theirs, missing="keep")
    assert r["total"] == 12 and r["kept"] == ["ВО/11-15/РГ"]
    assert show(ws, "ВО/11-15/БО")["act"]["manual"] == {"O": "Реестр 7"}


def test_drop_removes_and_remembers(ws, acts_xlsx, tmp_path):
    ingest(ws, [acts_xlsx])
    theirs = _copy_without(ws, tmp_path, "ВО/11-15/РГ")
    r = replace_registry(ws, theirs, missing="drop")
    assert r["total"] == 11 and r["dropped"] == ["ВО/11-15/РГ"]
    assert ingest(ws, [acts_xlsx])["total"] == 11            # удалённый им акт не возвращается сам


def test_edits_made_in_excel_survive_reingest(ws, acts_xlsx, tmp_path):
    ingest(ws, [acts_xlsx])
    theirs = tmp_path / "from_engineer.xlsx"
    shutil.copy(ws.registry_path, theirs)
    write_cell(theirs, number="ВО/11-15/БО", col=11, value="колодцы 11-15")       # поправил место прямо в Excel
    r = replace_registry(ws, theirs, missing="keep")
    assert r["manual_edits"] == 1
    ingest(ws, [acts_xlsx])
    assert show(ws, "ВО/11-15/БО")["act"]["place"] == "колодцы 11-15"


def test_replace_rejects_wrong_files(ws, acts_xlsx, tmp_path):
    assert code_of(lambda: replace_registry(ws, acts_xlsx)) == "bad_file"
    assert code_of(lambda: replace_registry(ws, ws.registry_path, missing="maybe")) == "bad_value"


def test_rows_without_document_are_not_carried_over(ws, small_template):
    """Шаблон инженера, присланный как реестр: остатки в служебных столбцах (L–R) не становятся строками акта."""
    from aosr.registry import C_PLACE, load
    r = replace_registry(ws, small_template, missing="keep")
    assert r["total"] == 1 and r["stray_rows"] == 20
    block = next(b for b in load(ws.registry_path) if b.key)
    assert block.rows == 10  # в примере из шаблона 9 строк приложений
    assert all(min(row) <= C_PLACE for row in block.tail)


def test_note_beside_an_appendix_is_kept(ws, small_template, tmp_path):
    """Заметка правее K в строке, где есть и сам документ, остаётся."""
    from aosr.registry import load
    def edit(wb):
        wb["общий"].cell(6, 13).value = "заметка"
    theirs = edit_book(small_template, tmp_path / "theirs.xlsx", edit)
    replace_registry(ws, theirs, missing="keep")
    block = next(b for b in load(ws.registry_path) if b.key)
    assert block.tail[0][13] == "заметка"


def test_blank_number_cell_does_not_start_a_document(ws, small_template, tmp_path):
    """Пробел в колонке номера у строки приложения: строка остаётся приложением своего акта."""
    from aosr.registry import C_NUM, load
    def edit(wb):
        wb["общий"].cell(8, C_NUM).value = " "
    theirs = edit_book(small_template, tmp_path / "theirs.xlsx", edit)
    r = replace_registry(ws, theirs, missing="keep")
    blocks = [b for b in load(ws.registry_path) if b.cells]
    assert r["total"] == 1 and len(blocks) == 1 and blocks[0].rows == 10
    assert all(C_NUM not in row for row in blocks[0].tail)
