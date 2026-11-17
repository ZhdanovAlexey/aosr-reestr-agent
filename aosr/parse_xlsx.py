"""Разбор актов в редактируемом формате: один лист книги — один акт."""
from __future__ import annotations

from datetime import date
from pathlib import Path

import openpyxl

from .errors import AosrError
from .model import Act, clean_number, parse_date, parse_item, parse_place, split_works


def _s(v) -> str:
    return "" if v is None else str(v).strip()


def _d(v) -> date | None:
    return parse_date(v)


def _find(ws, needle: str, col: int = 1, start: int = 1) -> int | None:
    for r in range(start, ws.max_row + 1):
        if needle in _s(ws.cell(r, col).value).lower():
            return r
    return None


def parse_sheet(ws, source: str) -> Act | None:
    head = _find(ws, "освидетельствования скрытых работ")
    if head is None:
        return None  # лист не похож на акт
    warnings: list[str] = []
    title = _s(ws.cell(head + 1, 1).value)
    number = clean_number(ws.cell(head + 2, 1).value)
    act_date = _d(ws.cell(head + 2, 9).value)
    if not number:
        warnings.append("не найден номер акта")
    if act_date is None:
        warnings.append("не найдена дата акта")

    act = Act(number=number, date=act_date, title=title, source=source, warnings=warnings)
    act.place, note = parse_place(title)
    if note:
        warnings.append(note)

    r = _find(ws, "к освидетельствованию предъявлены", start=head)
    if r is None:
        warnings.append("не найден п. 1 с перечнем работ")
    else:
        for line in split_works(ws.cell(r + 1, 1).value, title):
            item, ok = parse_item(line)
            if not ok:
                warnings.append(f"не выделено количество: «{line[:80]}»")
            act.items.append(item)
        if not act.items:
            warnings.append("в п. 1 нет строк работ")

    r = _find(ws, "произвели осмотр работ", start=head)
    if r is not None:
        act.organization = _s(ws.cell(r, 5).value)

    r = _find(ws, "5. даты", start=head)
    if r is not None:
        act.date_start, act.date_end = _d(ws.cell(r, 5).value), _d(ws.cell(r + 1, 5).value)

    r = _find(ws, "приложения:", start=head)
    if r is None:
        warnings.append("не найден список приложений")
    else:
        for rr in range(r + 1, ws.max_row + 1):
            n = _s(ws.cell(rr, 1).value)
            if not n.isdigit():
                break
            text = _s(ws.cell(rr, 2).value)
            if text and text.lower() != "hide":
                act.appendices.append(text)
    return act


def parse_workbook(path: str | Path) -> tuple[list[Act], list[str]]:
    """Акты книги и записи о листах, которые не похожи на акт."""
    path = Path(path)
    try:
        wb = openpyxl.load_workbook(path, data_only=True)
    except Exception as e:  # не архив, битый файл, не тот формат
        raise AosrError("bad_file", f"{path.name}: не удалось открыть как книгу xlsx ({type(e).__name__})") from e
    acts, skipped = [], []
    for ws in wb.worksheets:
        act = parse_sheet(ws, f"{path.name} / лист «{ws.title}»")
        if act is None:
            skipped.append(f"лист «{ws.title}» не похож на акт")
        else:
            acts.append(act)
    return acts, skipped
