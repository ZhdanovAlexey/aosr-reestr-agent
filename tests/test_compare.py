from datetime import date

from aosr.compare import compare_acts, diff_fragments
from aosr.model import WorkItem
from aosr.scan import to_act

D = date(2024, 8, 13)
I1 = WorkItem("3.2.1.24", "Уплотнение грунта", "812,45", "м3")
I2 = WorkItem("3.2.1.25", "Полив водой", "812,45", "м3")


def test_recorded_answers_disagree_only_where_models_misread(raw_primary, raw_secondary):
    qs = compare_acts(to_act(raw_primary, "x"), to_act(raw_secondary, "x"))
    fields = [q["field"] for q in qs]
    assert "code" in fields and all(f == "code" or f.startswith("appendix.") for f in fields)   # номер, дата, работы, объёмы совпали
    code = next(q for q in qs if q["field"] == "code")
    assert code["fragments"] == ["3.2.1.4", "3.2.1.5"] and code["options"][1].split("\n")[1] == "3.2.1.5"
    assert all(len(f) < 120 for q in qs for f in q["fragments"])
    assert all(q["kind"] == "mismatch" for q in qs)


def test_identical_acts_have_no_questions(make_act):
    assert compare_acts(make_act("X", D), make_act("X", D)) == []


def test_cosmetic_differences_are_not_questions(make_act):
    a = make_act("ЗР/ВГ/1", D, appendices=["Набор фотоизображений от 13.08.2024 - 4 листа;"])
    b = make_act("ЗР/ВГ/1", D, appendices=["набор  фотоизображений от 13.08.2024 – 4 листа"])
    assert compare_acts(a, b) == []


def test_qty_mismatch_is_short_question(make_act):
    a = make_act("X", D, items=[WorkItem("3.2.1.24", "Уплотнение", "812,45", "м3")])
    b = make_act("X", D, items=[WorkItem("3.2.1.24", "Уплотнение", "872,45", "м3")])
    assert compare_acts(a, b) == [{"kind": "mismatch", "field": "qty", "options": ["812,45", "872,45"], "fragments": ["812,45", "872,45"]}]


def test_number_and_date_mismatch(make_act):
    qs = compare_acts(make_act("ЗР/ВГ/1", D), make_act("ЗР/ВГ/7", date(2024, 8, 17)))
    assert [(q["field"], q["options"]) for q in qs] == [("number", ["ЗР/ВГ/1", "ЗР/ВГ/7"]), ("date", ["13.08.2024г.", "17.08.2024г."])]


def test_different_item_count_is_one_question(make_act):
    qs = compare_acts(make_act("X", D, items=[I1, I2]), make_act("X", D, items=[I1]))
    assert [q["field"] for q in qs] == ["items"]
    assert qs[0]["options"][0] == {"code": "3.2.1.24\n3.2.1.25", "work": "Уплотнение грунта\nПолив водой", "unit": "м3\nм3", "qty": "812,45\n812,45"}
    assert qs[0]["fragments"] == ["2 строки работ", "1 строка работ"]


def test_different_appendix_count_is_one_question(make_act):
    qs = compare_acts(make_act("X", D, appendices=["а", "б"]), make_act("X", D, appendices=["а"]))
    assert [(q["field"], q["options"]) for q in qs] == [("appendices", [["а", "б"], ["а"]])]


def test_long_field_shows_only_the_differing_fragment(make_act):
    a = "Протокол №СТЛ/1/ФМС/12.08 по результатам испытаний физико-механических свойств грунта от 12.08.2024 г. - 1 лист;"
    b = "Протокол №ССТЛ 1/ФМС/12.08 по результатам испытаний физико-механических свойств грунта от 12.08.2024 г. - 1 лист;"
    q = compare_acts(make_act("X", D, appendices=[a]), make_act("X", D, appendices=[b]))[0]
    assert (q["field"], q["options"]) == ("appendix.1", [a, b])
    assert q["fragments"] == ["Протокол №СТЛ/1/ФМС/12.08 по результатам испытаний …", "Протокол №ССТЛ 1/ФМС/12.08 по результатам испытаний …"]


def test_diff_fragments_in_the_middle():
    a = "один два три четыре пять ШЕСТЬ семь восемь девять десять одиннадцать"
    b = "один два три четыре пять ШЕСТ семь восемь девять десять одиннадцать"
    assert diff_fragments(a, b) == ["… три четыре пять ШЕСТЬ семь восемь девять …", "… три четыре пять ШЕСТ семь восемь девять …"]
