from __future__ import annotations

import shutil
from datetime import date
from pathlib import Path

import openpyxl
import pytest

from aosr.errors import AosrError
from aosr.model import Act, WorkItem, parse_place

ROOT = Path(__file__).resolve().parents[1]
# Синтетические примеры: scripts/make_examples.py
ACTS = ROOT / "examples" / "acts.xlsx"
TEMPLATE = ROOT / "examples" / "registry_template.xlsx"
SCAN = ROOT / "examples" / "act_scan.pdf"


def _need(path: Path) -> Path:
    if not path.exists():
        pytest.skip(f"нет входного файла {path.name}")
    return path


@pytest.fixture(scope="session")
def acts_xlsx() -> Path:
    return _need(ACTS)


@pytest.fixture(scope="session")
def template_xlsx() -> Path:
    return _need(TEMPLATE)


@pytest.fixture(scope="session")
def scan_pdf() -> Path:
    return _need(SCAN)


@pytest.fixture
def make_act():
    def make(number: str, d: date | None, **kw) -> Act:
        kw.setdefault("title", "Монтаж трубопровода на участке 1-2")
        kw.setdefault("items", [WorkItem("5.3.1.31", "Укладка труб", "10", "м")])
        kw.setdefault("appendices", ["Исполнительная схема - 1 лист;"])
        kw.setdefault("place", parse_place(kw["title"])[0])
        return Act(number=number, date=d, **kw)
    return make


def code_of(fn) -> str:
    with pytest.raises(AosrError) as e:
        fn()
    return e.value.code


def edit_book(src: Path, dst: Path, edit) -> Path:
    """Копия книги с правкой: edit(workbook)."""
    shutil.copy(src, dst)
    wb = openpyxl.load_workbook(dst)
    edit(wb)
    wb.save(dst)
    return dst


@pytest.fixture(scope="session")
def small_template(template_xlsx, tmp_path_factory) -> Path:
    """Шаблон без остальных листов книги — тот же лист «общий»; на больших рабочих книгах открывается в разы быстрее."""
    def edit(wb):
        for name in wb.sheetnames:
            if name != "общий":
                del wb[name]
    return edit_book(template_xlsx, tmp_path_factory.mktemp("tpl") / "template.xlsx", edit)


@pytest.fixture
def ws(tmp_path, small_template):
    """Рабочая папка с чистым реестром."""
    from aosr.store import Workspace
    w = Workspace(tmp_path / "home")
    w.init(small_template)
    return w


@pytest.fixture
def fake_scan(tmp_path):
    """Подделка разбора скана: read_scan, возвращающий заданный акт ЗР/ВГ/1 и заготовки вопросов."""
    def make(qty: str = "812,45", qty_options: list[str] | None = None, appendix_options: list[str] | None = None):
        def read_scan(path):
            q = qty_options[0] if qty_options else qty
            act = Act(number="ЗР/ВГ/1", date=date(2024, 8, 13), title="Разработка грунта в выемке",
                      items=[WorkItem("3.2.1.24", "Уплотнение грунта", q, "м3")],
                      appendices=[appendix_options[0] if appendix_options else "Акт отбора проб №СТЛ/1/ФМС/12.08 - 1 лист;"],
                      origin="scan", source=str(path), warnings=["из скана — сверь с оригиналом"])
            drafts = []
            if qty_options:
                drafts.append({"kind": "mismatch", "field": "qty", "options": qty_options, "fragments": qty_options})
            if appendix_options:
                drafts.append({"kind": "mismatch", "field": "appendix.1", "options": appendix_options, "fragments": ["СТЛ/1/ФМС", "ССТЛ 1/ФМС"]})
            return act, drafts, []
        return read_scan
    return make


@pytest.fixture
def pdf(tmp_path) -> Path:
    p = tmp_path / "scan.pdf"
    p.write_bytes(b"%PDF-fake")
    return p


FIXTURES = Path(__file__).parent / "fixtures" / "scan_example"
PRIMARY, SECONDARY = "qwen3.6-fp8-noreason", "qwen3.8-27b-noreason"


def _raw(model: str) -> dict:
    import json
    p = FIXTURES / f"{model}.json"
    if not p.exists():
        pytest.skip(f"нет записанного ответа {p.name} — scripts/record_scan_fixture.py")
    return json.loads(p.read_text(encoding="utf-8"))


@pytest.fixture
def raw_primary() -> dict:
    return _raw(PRIMARY)


@pytest.fixture
def raw_secondary() -> dict:
    return _raw(SECONDARY)


@pytest.fixture
def chat_from_fixtures():
    """Подмена вызова модели записанными ответами на образец ЗР/ВГ/1."""
    return lambda model, prompt, images, **kw: _raw(model)


@pytest.fixture
def chat_failing_for():
    def make(*down: str):
        def chat(model, prompt, images, **kw):
            if model in down:
                raise AosrError("model_error", f"модель {model} недоступна: сеть")
            return _raw(model)
        return chat
    return make


@pytest.fixture
def one_page_pdf(tmp_path) -> Path:
    import pymupdf as fitz
    doc = fitz.open()
    doc.new_page().insert_text((72, 72), "AKT")
    p = tmp_path / "one.pdf"
    doc.save(p)
    return p
