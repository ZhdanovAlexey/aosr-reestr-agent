"""Чтение и запись листа «общий» реестра исполнительной документации.

Реестр — источник правды. Лист читается в блоки (строка документа + строки под ней),
блоки пересортировываются и записываются обратно. Любая непустая строка сохраняется
по значениям, в том числе строки документов, которые создавал не этот код.
"""
from __future__ import annotations

import math
import shutil
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path

import openpyxl
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.worksheet.cell_range import CellRange

from .errors import AosrError
from .model import DOC_NAME, Act, clean_number, norm_number, parse_date

SHEET = "общий"
HEADER_ROW = 4
FIRST_ROW = 5
LAST_COL = 16  # A..P
C_CODE, C_DOC, C_WORK, C_DATE, C_NUM, C_UNIT, C_QTY, C_PLACE = 4, 5, 6, 7, 8, 9, 10, 11
FIELD_COLS = {"code": C_CODE, "work": C_WORK, "date": C_DATE, "number": C_NUM,
              "unit": C_UNIT, "qty": C_QTY, "place": C_PLACE}
AUTO_COLS = (C_CODE, C_DOC, C_WORK, C_DATE, C_NUM, C_UNIT, C_QTY, C_PLACE)

_THIN = Side(style="thin")
_BORDER = Border(left=_THIN, right=_THIN, top=_THIN, bottom=_THIN)
_FONT_ACT = Font(name="Times New Roman", size=16, bold=True, italic=True)
_FONT_APP = Font(name="Times New Roman", size=16, italic=True)
_AL_CENTER = Alignment(horizontal="center", vertical="center", wrap_text=True)
_AL_LEFT = Alignment(horizontal="left", vertical="center", wrap_text=True)
_NO_FILL = PatternFill(fill_type=None)
_ROW_H_ACT, _ROW_H_APP, _LINE_H = 66.75, 49.95, 21.0


@dataclass
class Block:
    """Документ в реестре: строка документа (cells) и строки под ней (tail).

    Блок с пустыми cells — строки, стоящие до первого документа с номером.
    """
    cells: dict[int, object]
    tail: list[dict[int, object]] = field(default_factory=list)

    @property
    def key(self) -> str:
        return norm_number(self.cells.get(C_NUM))

    @property
    def is_act(self) -> bool:
        """Акт скрытых работ, а не другой документ, оказавшийся в реестре."""
        return bool(self.key) and str(self.cells.get(C_DOC, "")).strip().lower() == DOC_NAME.lower()

    @property
    def date(self) -> date | None:
        return parse_date(self.cells.get(C_DATE))

    @property
    def appendices(self) -> list[str]:
        return [str(r[C_WORK]) for r in self.tail if set(r) == {C_WORK}]

    @appendices.setter
    def appendices(self, texts: list[str]) -> None:
        other = [r for r in self.tail if set(r) != {C_WORK}]
        self.tail = [{C_WORK: t} for t in texts] + other

    @property
    def rows(self) -> int:
        return (1 if self.cells else 0) + len(self.tail)


def fmt_date(d: date | None) -> str:
    return f"{d:%d.%m.%Y}г." if d else ""


def act_cells(act: Act) -> dict[int, object]:
    """Ячейки строки акта по правилам, согласованным с инженером. Пустые значения не пишутся."""
    cells = {
        # пустые строки сохраняют место: код стоит напротив своей работы
        C_CODE: "\n".join(i.code for i in act.items).rstrip("\n"),
        C_DOC: DOC_NAME,
        C_WORK: "\n".join(i.name for i in act.items) or act.title,
        C_DATE: fmt_date(act.date),
        C_NUM: clean_number(act.number),
        C_UNIT: "\n".join(i.unit for i in act.items),
        C_QTY: "\n".join(i.qty for i in act.items),
        C_PLACE: act.place,
    }
    return {c: v for c, v in cells.items() if v != ""}


def sort_blocks(blocks: list[Block]) -> list[Block]:
    """По дате, затем по номеру. Строки без документа — первыми, документы без даты — в конец."""
    head = [b for b in blocks if not b.cells]
    dated = sorted((b for b in blocks if b.cells and b.date), key=lambda b: (b.date, b.key))
    undated = [b for b in blocks if b.cells and not b.date]
    return head + dated + undated


def _open(path: str | Path):
    try:
        wb = openpyxl.load_workbook(path)
    except Exception as e:
        raise AosrError("bad_file", f"{Path(path).name}: не удалось открыть как книгу xlsx ({type(e).__name__})") from e
    if SHEET not in wb.sheetnames:
        raise AosrError("bad_file", f"{Path(path).name}: в книге нет листа «{SHEET}»")
    return wb, wb[SHEET]


def is_registry(path: str | Path) -> bool:
    """Книга с листом «общий» и шапкой таблицы реестра."""
    try:
        wb = openpyxl.load_workbook(path, read_only=True)
    except Exception:
        return False
    try:
        if SHEET not in wb.sheetnames:
            return False
        for row in wb[SHEET].iter_rows(min_row=HEADER_ROW, max_row=HEADER_ROW, max_col=LAST_COL, values_only=True):
            return any(str(v or "").strip() == "Наименование документа" for v in row)
        return False
    finally:
        wb.close()


def footer_row(ws) -> int:
    """Строка «Сдал:» под таблицей; если её нет — первая строка за данными."""
    for r in range(FIRST_ROW, ws.max_row + 1):
        if str(ws.cell(r, 1).value or "").strip().lower().startswith("сдал"):
            return r
    return ws.max_row + 1


def _width(ws) -> int:
    """Сколько колонок переносить вместе со строкой: заметки правее P едут со своим документом."""
    return max(LAST_COL, ws.max_column)


def _cell_value(value, col: int):
    """Настоящая дата Excel становится текстом: в колонке даты акта — как у остальных актов."""
    if isinstance(value, (datetime, date)):
        d = value.date() if isinstance(value, datetime) else value
        return fmt_date(d) if col == C_DATE else f"{d:%d.%m.%Y}"
    return value


def _read(ws, footer: int) -> list[Block]:
    blocks: list[Block] = []
    width = _width(ws)
    for r in range(FIRST_ROW, footer):
        row = {c: _cell_value(ws.cell(r, c).value, c) for c in range(1, width + 1)}
        # ячейка из одних пробелов пуста: иначе пробел в колонке номера начинает «документ» посреди приложений
        row = {c: v for c, v in row.items() if v is not None and str(v).strip()}
        if not row:
            continue
        if C_NUM in row:
            blocks.append(Block(cells=row))
        else:
            if not blocks:
                blocks.append(Block(cells={}))
            blocks[-1].tail.append(row)
    return blocks


def drop_stray(blocks: list[Block]) -> int:
    """Убрать строки, где нет ничего в колонках документа (A–K): остатки в служебных колонках чужого файла.

    Такая строка не принадлежит ни одному документу; после пересортировки она оказалась бы под случайным актом.
    Возвращает число убранных строк.
    """
    dropped = 0
    for b in blocks:
        keep = [row for row in b.tail if min(row) <= C_PLACE]
        dropped += len(b.tail) - len(keep)
        b.tail = keep
    return dropped


def load(path: str | Path) -> list[Block]:
    _, ws = _open(path)
    return _read(ws, footer_row(ws))


def _lines(text, width: int) -> int:
    return sum(max(1, math.ceil(len(l) / width)) for l in str(text or "").split("\n"))


def _style_row(ws, r: int, head: bool) -> None:
    for c in range(1, LAST_COL + 1):
        cell = ws.cell(r, c)
        cell.border = _BORDER
        cell.fill = _NO_FILL
        if not head and c == C_WORK:
            cell.font, cell.alignment = _FONT_APP, _AL_LEFT
        else:
            cell.font, cell.alignment = _FONT_ACT, _AL_CENTER
        cell.number_format = "General"


def _make_room(ws, footer: int, need: int) -> int:
    """Раздвинуть таблицу, если блоки не помещаются до подписей. Вернуть новую строку подписей."""
    free = footer - FIRST_ROW
    if need <= free:
        return footer
    extra = need - free
    below = [CellRange(str(m)) for m in list(ws.merged_cells.ranges) if m.min_row >= footer]
    for m in below:
        ws.unmerge_cells(str(m))
    heights = {r: ws.row_dimensions[r].height for r in range(footer, ws.max_row + 1) if ws.row_dimensions[r].height}
    ws.insert_rows(footer, extra)
    for m in below:
        m.shift(row_shift=extra)
        ws.merge_cells(str(m))
    for r, h in heights.items():
        ws.row_dimensions[r + extra].height = h
    return footer + extra


def _clear(ws, footer: int) -> None:
    for m in list(ws.merged_cells.ranges):
        if m.max_row >= FIRST_ROW and m.min_row < footer:
            ws.unmerge_cells(str(m))
    width = _width(ws)  # считается один раз: max_column обходит весь лист
    for r in range(FIRST_ROW, footer):
        for c in range(1, width + 1):
            ws.cell(r, c).value = None


def _write(ws, blocks: list[Block]) -> None:
    footer = _make_room(ws, footer_row(ws), sum(b.rows for b in blocks))
    _clear(ws, footer)
    r = FIRST_ROW
    for b in blocks:
        if b.cells:
            for c, v in b.cells.items():
                ws.cell(r, c).value = v
            _style_row(ws, r, head=True)
            n = max(_lines(b.cells.get(C_WORK), 95), _lines(b.cells.get(C_PLACE), 40),
                    _lines(b.cells.get(C_CODE), 16), _lines(b.cells.get(C_NUM), 55))
            ws.row_dimensions[r].height = max(_ROW_H_ACT, n * _LINE_H + 8)
            r += 1
        for row in b.tail:
            for c, v in row.items():
                ws.cell(r, c).value = v
            _style_row(ws, r, head=False)
            ws.row_dimensions[r].height = max(_ROW_H_APP, _lines(row.get(C_WORK), 95) * _LINE_H + 8)
            r += 1
    if ws.auto_filter.ref:
        ws.auto_filter.ref = f"A{HEADER_ROW}:M{max(r - 1, FIRST_ROW)}"


def save(path: str | Path, blocks: list[Block], out: str | Path) -> None:
    """Записать блоки в книгу path и сохранить в out (можно тот же файл)."""
    wb, ws = _open(path)
    _write(ws, blocks)
    tmp = Path(out).with_suffix(".tmp.xlsx")
    wb.save(tmp)
    shutil.move(tmp, out)


def init_registry(template: str | Path, out: str | Path) -> None:
    """Чистый реестр из шаблона: область данных (включая пример и остатки старых данных) очищается."""
    wb, ws = _open(template)
    _clear(ws, footer_row(ws))
    wb.save(out)
