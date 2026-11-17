from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from datetime import date

DOC_NAME = "Акт освидетельствования скрытых работ"

_NUM = r"\d[\d\s]*(?:[.,]\d+)?"
_UNIT = r"[A-Za-zА-Яа-я][A-Za-zА-Яа-я./]*\d?"
# «... - 87,5 м.»  — количество после последнего тире
# Вокруг тире нужен пробел хотя бы с одной стороны: «фр. 20-40 мм» и «d-110 мм» — размеры, а не количество.
_TAIL_DASH = re.compile(rf"^(?P<name>.+?)(?:\s+[-–—]\s*|[-–—]\s+)(?P<qty>{_NUM})\s*(?P<unit>{_UNIT})[\s.;,]*$")
# «... (V=2,07 м3)» или «... V=1640,2 м3» — количество через обозначение величины
_TAIL_EQ = re.compile(rf"^(?P<name>.+?)\s*\(?\s*[VSLNМ]\s*=\s*(?P<qty>{_NUM})\s*(?P<unit>{_UNIT})\s*\)?[\s.;,]*$")
_CODE = re.compile(r"^(?P<code>\d+(?:\.\d+)+)\.?\s+(?P<rest>.+)$")
_PLACE_SITE = re.compile(r"на\s+участк(?:е|ах)\s+(?P<place>.+)$", re.I)
_PLACE_WELLS = re.compile(r"колодц(?:ев|ы|ам|а)\s+(?P<place>.+)$", re.I)


@dataclass
class WorkItem:
    code: str  # № по ведомости, пусто для работ вне контрактной ведомости
    name: str
    qty: str
    unit: str


@dataclass
class Act:
    number: str
    date: date | None
    title: str
    place: str = ""
    items: list[WorkItem] = field(default_factory=list)
    appendices: list[str] = field(default_factory=list)
    organization: str = ""
    date_start: date | None = None
    date_end: date | None = None
    source: str = ""
    warnings: list[str] = field(default_factory=list)
    origin: str = "xlsx"  # "xlsx" или "scan"

    @property
    def key(self) -> str:
        return norm_number(self.number)

    def to_dict(self) -> dict:
        d = asdict(self)
        for k in ("date", "date_start", "date_end"):
            d[k] = d[k].isoformat() if d[k] else None
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "Act":
        d = dict(d)
        for k in ("date", "date_start", "date_end"):
            d[k] = date.fromisoformat(d[k]) if d.get(k) else None
        d["items"] = [WorkItem(**i) for i in d.get("items", [])]
        return cls(**d)


_RU_MONTHS = {m: i + 1 for i, m in enumerate(
    ["январ", "феврал", "март", "апрел", "ма", "июн", "июл", "август", "сентябр", "октябр", "ноябр", "декабр"])}


def parse_date(v) -> date | None:
    """Дата из значения ячейки или текста: 19.02.2025, «19.02.2025г.», «13 августа 2024 г.»."""
    if hasattr(v, "date") and callable(v.date):
        return v.date()
    if isinstance(v, date):
        return v
    s = str(v or "").strip().lower()
    m = re.search(r"(\d{1,2})\.(\d{1,2})\.(\d{4})", s)
    try:
        if m:
            return date(int(m.group(3)), int(m.group(2)), int(m.group(1)))
        m = re.search(r"(\d{1,2})\s+([а-яё]+)\s+(\d{4})", s)
        if m:
            for stem, num in sorted(_RU_MONTHS.items(), key=lambda kv: -len(kv[0])):
                if m.group(2).startswith(stem):
                    return date(int(m.group(3)), num, int(m.group(1)))
    except ValueError:
        return None
    return None


def norm_number(number: str) -> str:
    """Ключ для поиска дублей: без «№», пробелов и регистра."""
    return re.sub(r"[\s№]", "", str(number or "")).upper()


def clean_number(number: str) -> str:
    return re.sub(r"^\s*№\s*", "", str(number or "")).strip()


def parse_item(line: str) -> tuple[WorkItem, bool]:
    """Разобрать строку работ. Второе значение — удалось ли выделить количество."""
    line = re.sub(r"\s+", " ", line).strip()
    code, rest = "", line
    m = _CODE.match(line)
    if m:
        code, rest = m.group("code"), m.group("rest")
    for pat in (_TAIL_EQ, _TAIL_DASH):
        m = pat.match(rest)
        if m:
            qty = re.sub(r"\s+", "", m.group("qty"))
            unit = m.group("unit").rstrip(".")
            return WorkItem(code, m.group("name").strip(" -–—"), qty, unit), True
    return WorkItem(code, rest.rstrip(" ;."), "", ""), False


def parse_place(title: str) -> tuple[str, str | None]:
    """Место освидетельствования из названия работ. Второе значение — замечание."""
    title = re.sub(r"\s+", " ", title).strip()
    m = _PLACE_SITE.search(title)
    if m:
        return m.group("place").strip(), None
    m = _PLACE_WELLS.search(title)
    if m:
        return m.group("place").strip(), "в названии нет «на участке», место взято после слова «колодцев»"
    return "", "не удалось выделить место освидетельствования из названия работ"


def split_works(text: str, title: str) -> list[str]:
    """Строки работ из п. 1 акта без повторённого названия акта."""
    lines = [re.sub(r"\s+", " ", l).strip() for l in str(text or "").split("\n")]
    lines = [l for l in lines if l]
    t = re.sub(r"\s+", " ", title).strip()
    if lines and lines[0] == t:
        lines = lines[1:]
    return lines
