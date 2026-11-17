from datetime import date

import pytest

from aosr.errors import AosrError
from aosr.parse_xlsx import parse_workbook
from conftest import edit_book


def test_all_sheets_parsed(acts_xlsx):
    acts, skipped = parse_workbook(acts_xlsx)
    assert len(acts) == 12 and skipped == []
    assert len({a.key for a in acts}) == 12
    for a in acts:
        assert a.number and a.date and a.items and a.appendices, a.source
        assert all(i.qty and i.unit for i in a.items), a.source


def test_text_date_is_parsed(tmp_path, acts_xlsx):
    def edit(wb):
        wb.worksheets[0]["I16"].value = "19.02.2025"
    acts, _ = parse_workbook(edit_book(acts_xlsx, tmp_path / "b.xlsx", edit))
    assert acts[0].date == date(2025, 2, 19) and "не найдена дата акта" not in acts[0].warnings


def test_non_act_sheets_are_reported(tmp_path, acts_xlsx):
    def edit(wb):
        wb.create_sheet("Справка")["A1"].value = "просто текст"
    acts, skipped = parse_workbook(edit_book(acts_xlsx, tmp_path / "b.xlsx", edit))
    assert len(acts) == 12 and skipped == ["лист «Справка» не похож на акт"]


def test_not_a_workbook(tmp_path):
    p = tmp_path / "x.xlsx"
    p.write_text("не архив")
    with pytest.raises(AosrError) as e:
        parse_workbook(p)
    assert e.value.code == "bad_file"
