"""Скан акта (PDF без текстового слоя) → акт. Модель только переписывает текст; поля выделяет общий код."""
from __future__ import annotations

import os
import re
from pathlib import Path

from .errors import AosrError
from .llm import chat_json
from .model import Act, clean_number, parse_date, parse_item, parse_place

PRIMARY_MODEL = os.environ.get("AOSR_SCAN_PRIMARY", "qwen3.6-fp8-noreason")
SECONDARY_MODEL = os.environ.get("AOSR_SCAN_SECONDARY", "qwen3.8-27b-noreason")

PROMPT = """Перед тобой первые страницы скана акта освидетельствования скрытых работ.
Перепиши из него поля. Верни строго один JSON-объект без пояснений:
{"номер_акта": "", "дата_акта": "ДД.ММ.ГГГГ", "название_работ": "",
 "работы": ["каждая строка пункта 1 целиком, с номером по ведомости и количеством, как в документе"],
 "приложения": ["каждая строка раздела «Приложения» целиком, с числом листов"],
 "есть_подписи": true}
«название_работ» — строка под заголовком «АКТ освидетельствования скрытых работ».
«есть_подписи» — true, если на этих страницах есть блок подписей представителей.
Переписывай цифры, номера и знаки «/» в точности как в документе. Ничего не додумывай и не исправляй.
Если поля нет в документе — пустая строка или пустой список."""

# строки бланка, которые модель иногда переписывает вместе с работами
_FORM_LINE = re.compile(r"к освидетельствованию предъявлены|^\(?наименование скрытых работ\)?$", re.I)
_STR_FIELDS =("номер_акта", "дата_акта", "название_работ")
_LIST_FIELDS = ("работы", "приложения")
_LEADING_NUMBER = re.compile(r"^\s*\d{1,2}[.)]?\s+")


def render_pages(pdf: str | Path, pages: int = 2, dpi: int = 200) -> list[bytes]:
    """JPEG первых страниц PDF."""
    import pymupdf as fitz

    pdf = Path(pdf)
    try:
        doc = fitz.open(pdf)
        if not doc.is_pdf:
            raise ValueError("не PDF")
        out = [doc[i].get_pixmap(dpi=dpi).tobytes("jpeg") for i in range(min(pages, doc.page_count))]
    except Exception as e:
        raise AosrError("bad_file", f"{pdf.name}: не удалось открыть как PDF ({type(e).__name__})") from e
    if not out:
        raise AosrError("bad_file", f"{pdf.name}: в PDF нет страниц")
    return out


def transcribe(images: list[bytes], model: str, *, chat=chat_json) -> dict:
    """Ответ модели, проверенный по схеме."""
    raw = chat(model, PROMPT, images)
    ok = (isinstance(raw, dict)
          and all(isinstance(raw.get(k), str) for k in _STR_FIELDS)
          and all(isinstance(raw.get(k), list) and all(isinstance(x, str) for x in raw[k]) for k in _LIST_FIELDS)
          and isinstance(raw.get("есть_подписи"), bool))
    if not ok:
        raise AosrError("model_error", f"модель {model} вернула ответ не по схеме акта")
    return raw


def to_act(raw: dict, source: str) -> Act:
    warnings = ["из скана — сверь с оригиналом"]
    if not raw["есть_подписи"]:
        warnings.append("возможно, не весь акт на первых двух страницах (нет блока подписей)")
    title = re.sub(r"\s+", " ", raw["название_работ"]).strip()
    number = clean_number(raw["номер_акта"])
    act_date = parse_date(raw["дата_акта"])
    if not number:
        warnings.append("не найден номер акта")
    if act_date is None:
        warnings.append("не найдена дата акта")
    act = Act(number=number, date=act_date, title=title, source=source, warnings=warnings, origin="scan")
    act.place, note = parse_place(title)
    if note:
        warnings.append(note)
    for line in raw["работы"]:
        flat = re.sub(r"\s+", " ", line).strip()
        if not flat or flat == title or _FORM_LINE.search(flat):
            continue
        item, ok = parse_item(line)
        if not ok:
            warnings.append(f"не выделено количество: «{line[:80]}»")
        act.items.append(item)
    if not act.items:
        warnings.append("в п. 1 нет строк работ")
    act.appendices = [t for t in (_LEADING_NUMBER.sub("", a).strip() for a in raw["приложения"]) if t]
    return act


def read_scan(pdf: str | Path, *, chat=chat_json) -> tuple[Act, list[dict], list[str]]:
    """Прочитать скан двумя моделями. Возвращает акт основной модели, заготовки вопросов и заметки."""
    from concurrent.futures import ThreadPoolExecutor

    from .compare import compare_acts

    pdf = Path(pdf)
    images = render_pages(pdf)

    def one(model: str):
        try:
            return to_act(transcribe(images, model, chat=chat), pdf.name)
        except AosrError as e:
            if e.code != "model_error":
                raise
            return e

    with ThreadPoolExecutor(2) as pool:
        first, second = pool.map(one, (PRIMARY_MODEL, SECONDARY_MODEL))
    if isinstance(first, AosrError) and isinstance(second, AosrError):
        raise AosrError("model_error", f"{pdf.name}: обе модели не справились ({first.message}; {second.message})")
    if isinstance(second, AosrError):
        return first, [], [f"проверено одной моделью: {SECONDARY_MODEL} недоступна"]
    if isinstance(first, AosrError):
        return second, [], [f"проверено одной моделью: {PRIMARY_MODEL} недоступна"]
    return first, compare_acts(first, second), []
