from datetime import date

import openpyxl

from aosr.model import WorkItem
from aosr.registry import (FIRST_ROW, Block, act_cells, footer_row, init_registry, is_registry, load, save,
                           sort_blocks)


def test_init_clears_template(tmp_path, template_xlsx):
    out = tmp_path / "r.xlsx"
    init_registry(template_xlsx, out)
    assert load(out) == [] and is_registry(out)
    assert "справочник" in openpyxl.load_workbook(out, read_only=True).sheetnames   # остальные листы книги на месте


def test_foreign_rows_survive(tmp_path, small_template, make_act):
    out = tmp_path / "r.xlsx"
    init_registry(small_template, out)
    foreign = Block(cells={5: "Общий журнал работ", 8: "ОЖР-1", 12: "01.07.2024г."},
                    tail=[{6: "Том 1 - 96 листов"}, {6: "примечание", 14: "ООО «Ромашка»"}])
    ours = Block(cells=act_cells(make_act("ВО/1", date(2024, 7, 11))), tail=[{6: "Схема - 1 лист;"}])
    save(out, sort_blocks([foreign, ours]), out)
    blocks = load(out)
    got = {b.key: b for b in blocks}
    assert got["ОЖР-1"].cells[12] == "01.07.2024г."
    assert got["ОЖР-1"].tail == foreign.tail
    assert got["ОЖР-1"].appendices == ["Том 1 - 96 листов"]
    assert [b.key for b in blocks] == ["ВО/1", "ОЖР-1"]


def test_rows_before_first_numbered_row_survive(tmp_path, small_template, make_act):
    out = tmp_path / "r.xlsx"
    init_registry(small_template, out)
    head = Block(cells={}, tail=[{6: "Раздел 1. Ливневая канализация"}])
    ours = Block(cells=act_cells(make_act("ВО/1", date(2024, 7, 11))), tail=[])
    save(out, sort_blocks([ours, head]), out)
    blocks = load(out)
    assert [b.key for b in blocks] == ["", "ВО/1"] and blocks[0].tail == head.tail


def test_setting_appendices_keeps_other_tail_rows():
    b = Block(cells={8: "X"}, tail=[{6: "a"}, {6: "note", 14: "org"}, {6: "b"}])
    b.appendices = ["c"]
    assert b.tail == [{6: "c"}, {6: "note", 14: "org"}]


def test_act_cells_follow_agreed_rules(make_act):
    a = make_act("№ВО/21-31/МТ", date(2025, 2, 19), title="Монтаж трубопровода на участке ДК21 - 7",
                 items=[WorkItem("5.3.1.31", "Укладка", "87,5", "м"), WorkItem("", "Муфта", "12", "шт")])
    assert act_cells(a) == {4: "5.3.1.31", 5: "Акт освидетельствования скрытых работ", 6: "Укладка\nМуфта",
                            7: "19.02.2025г.", 8: "ВО/21-31/МТ", 9: "м\nшт", 10: "87,5\n12", 11: "ДК21 - 7"}


def test_sort_by_date_then_number(make_act):
    mk = lambda n, d: Block(cells=act_cells(make_act(n, d)), tail=[])
    blocks = sort_blocks([mk("Б/2", date(2025, 1, 1)), mk("А/9", date(2024, 1, 1)), mk("А/1", date(2025, 1, 1))])
    assert [b.key for b in blocks] == ["А/9", "А/1", "Б/2"]


def test_manual_columns_roundtrip(tmp_path, small_template, make_act):
    out = tmp_path / "r.xlsx"
    init_registry(small_template, out)
    b = Block(cells={**act_cells(make_act("ВО/1", date(2024, 7, 11))), 1: "КС-3", 15: "Реестр 7"}, tail=[])
    save(out, [b], out)
    assert load(out)[0].cells[15] == "Реестр 7" and load(out)[0].cells[1] == "КС-3"


def test_overflow_moves_signatures(tmp_path, small_template, make_act):
    out = tmp_path / "r.xlsx"
    init_registry(small_template, out)
    blocks = [Block(cells=act_cells(make_act(f"Т/{n}", date(2025, 1, 1))), tail=[{6: f"прил {k}"} for k in range(9)])
              for n in range(201)]
    save(out, sort_blocks(blocks), out)
    ws = openpyxl.load_workbook(out)["общий"]
    footer = footer_row(ws)
    assert len(load(out)) == 201
    assert footer >= FIRST_ROW + 201 * 10
    assert str(ws.cell(footer, 1).value).startswith("Сдал")
    assert f"A{footer}:B{footer}" in [str(m) for m in ws.merged_cells.ranges]


def test_is_registry(acts_xlsx, template_xlsx, tmp_path):
    assert is_registry(template_xlsx) and not is_registry(acts_xlsx)
    junk = tmp_path / "x.xlsx"
    junk.write_text("не архив")
    assert not is_registry(junk)
