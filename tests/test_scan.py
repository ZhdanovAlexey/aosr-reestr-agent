from datetime import date

import pytest

from aosr.errors import AosrError
from aosr.scan import render_pages, to_act, transcribe

MINIMAL = {"номер_акта": "№ ЗР/ВГ/1", "дата_акта": "13.08.2024", "название_работ": "Выемка грунта на участке 5-7",
           "работы": ["3.2.1.3 Разработка грунта (выемка) V=1640,2 м3"], "приложения": ["1 Схема - 8 листов;"],
           "есть_подписи": True}


def test_to_act_minimal():
    a = to_act(MINIMAL, "x.pdf")
    assert (a.number, a.date, a.origin, a.source, a.place) == ("ЗР/ВГ/1", date(2024, 8, 13), "scan", "x.pdf", "5-7")
    assert [(i.code, i.name, i.qty, i.unit) for i in a.items] == [("3.2.1.3", "Разработка грунта (выемка)", "1640,2", "м3")]
    assert a.appendices == ["Схема - 8 листов;"]
    assert a.warnings == ["из скана — сверь с оригиналом"]


def test_to_act_from_recorded_answer(raw_primary):
    a = to_act(raw_primary, "АОСР.pdf")
    assert (a.number, a.date, a.origin) == ("ЗР/ВГ/1", date(2024, 8, 13), "scan")
    assert [(i.qty, i.unit) for i in a.items] == [("1640,2", "м3"), ("1490,6", "м3"), ("812,45", "м3"), ("812,45", "м3"), ("1530,7", "м2")]
    # В документе вторая позиция — 3.2.1.5. Основная модель в записанном прогоне прочла «3.2.1.4»:
    # это настоящая ошибка распознавания, её ловит сверка со второй моделью (tests/test_compare.py).
    assert [i.code for i in a.items] == ["3.2.1.3", "3.2.1.4", "3.2.1.24", "3.2.1.25", "3.2.1.27"]
    assert a.place == "" and len(a.appendices) == 6
    assert not a.appendices[1][0].isdigit()
    assert "из скана — сверь с оригиналом" in a.warnings


def test_second_model_reads_the_code_correctly(raw_secondary):
    assert [i.code for i in to_act(raw_secondary, "x").items] == ["3.2.1.3", "3.2.1.5", "3.2.1.24", "3.2.1.25", "3.2.1.27"]


def test_russian_month_date():
    assert to_act({**MINIMAL, "дата_акта": "13 августа 2024 г."}, "x").date == date(2024, 8, 13)


def test_no_signatures_is_flagged():
    assert any("не весь акт" in w for w in to_act({**MINIMAL, "есть_подписи": False}, "x").warnings)


def test_missing_fields_are_flagged_not_fatal():
    a = to_act({**MINIMAL, "номер_акта": "", "дата_акта": "", "работы": []}, "x")
    assert {"не найден номер акта", "не найдена дата акта", "в п. 1 нет строк работ"} <= set(a.warnings)


@pytest.mark.parametrize("bad", [{"номер_акта": 5}, {**MINIMAL, "работы": "строка"}, {**MINIMAL, "приложения": [1]},
                                 {k: v for k, v in MINIMAL.items() if k != "есть_подписи"}])
def test_schema_violation_is_model_error(bad):
    with pytest.raises(AosrError) as e:
        transcribe([b"x"], "m", chat=lambda *a, **k: bad)
    assert e.value.code == "model_error"


def test_transcribe_passes_prompt_and_images():
    seen = {}
    def chat(model, prompt, images, **kw):
        seen.update(model=model, prompt=prompt, images=images)
        return MINIMAL
    assert transcribe([b"a", b"b"], "m1", chat=chat) == MINIMAL
    assert seen["model"] == "m1" and seen["images"] == [b"a", b"b"] and "есть_подписи" in seen["prompt"]


def test_render_example_pdf(scan_pdf):
    pages = render_pages(scan_pdf)
    assert len(pages) == 2 and pages[0][:2] == b"\xff\xd8"


def test_render_rejects_non_pdf(tmp_path):
    p = tmp_path / "x.pdf"
    p.write_text("не pdf")
    with pytest.raises(AosrError) as e:
        render_pages(p)
    assert e.value.code == "bad_file"


def test_one_page_pdf_is_accepted(one_page_pdf):
    assert len(render_pages(one_page_pdf)) == 1


def test_section_heading_is_not_a_work_line():
    raw = {**MINIMAL, "работы": ["1. К освидетельствованию предъявлены следующие работы:", *MINIMAL["работы"], "(наименование скрытых работ)"]}
    a = to_act(raw, "x")
    assert [i.code for i in a.items] == ["3.2.1.3"] and a.warnings == ["из скана — сверь с оригиналом"]
