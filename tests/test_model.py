from datetime import date

from aosr.model import Act, WorkItem, parse_item, parse_place


def test_code_dash():
    it, ok = parse_item("5.3.1.31 Укладка труб. Труба ПП гофр. ID300 SN16 - 87,5 м.")
    assert ok
    assert (it.code, it.name, it.qty, it.unit) == ("5.3.1.31", "Укладка труб. Труба ПП гофр. ID300 SN16", "87,5", "м")


def test_dashes_and_units_inside_name():
    it, ok = parse_item("6.1.1.1 Разработка грунта экскаватором с ковшом 1 (1-1,2) м3 с погрузкой, группа грунтов: 2 (влажный грунт) - 128,26 м3;")
    assert ok and (it.qty, it.unit) == ("128,26", "м3")
    assert it.name.endswith("(влажный грунт)")


def test_glued_dash():
    it, ok = parse_item("6.1.1.10 Засыпка вручную траншей, группа грунтов: 1- 47,01 м3;")
    assert (ok, it.qty, it.name[-17:]) == (True, "47,01", "группа грунтов: 1")


def test_no_code_volume_in_brackets():
    it, ok = parse_item("Устройство бетонного основания под колодцы 12, 13, 14, 15, 16 (V=2,07 м3)")
    assert (ok, it.code, it.qty, it.unit) == (True, "", "2,07", "м3")
    assert it.name == "Устройство бетонного основания под колодцы 12, 13, 14, 15, 16"


def test_scan_style():
    it, ok = parse_item("3.2.1.27 Планировка откосов: выемок экскаватором-планировщиком, группа грунтов 2 S=1530,7 м2")
    assert (ok, it.code, it.qty, it.unit) == (True, "3.2.1.27", "1530,7", "м2")


def test_unparsed():
    it, ok = parse_item("Что-то без количества")
    assert not ok and it.name == "Что-то без количества"


def test_place_site():
    assert parse_place("Монтаж трубопровода на участке ДК21 - 7, ДК23 - 8") == ("ДК21 - 7, ДК23 - 8", None)
    assert parse_place("Выемка грунта на участках 11-15 ")[0] == "11-15"


def test_place_wells_flagged():
    place, note = parse_place("Устройство бетонной подготовки колодцев 11-15")
    assert place == "11-15" and note is not None


def test_act_roundtrip(make_act):
    a = make_act("ВО/1", date(2025, 2, 19), items=[WorkItem("5.3.1.31", "Укладка", "87,5", "м")], appendices=["Схема - 1 лист;"])
    assert Act.from_dict(a.to_dict()) == a
    assert a.to_dict()["date"] == "2025-02-19" and a.origin == "xlsx"
