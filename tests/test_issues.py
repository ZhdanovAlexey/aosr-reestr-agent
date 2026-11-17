from aosr.compare import normalize
from aosr.ops import delete, ingest, issues, resolve, show, summary, undo
from conftest import code_of


def test_normalize():
    assert normalize("  Акт  отбора проб №СТЛ / 1 /ФМС «12.08» — 1 лист; ") == 'акт отбора проб №стл/1/фмс "12.08"-1 лист'
    assert normalize("Ёмкость") == "емкость"
    assert normalize(None) == ""


def test_mismatch_goes_to_registry_with_primary_value(ws, pdf, fake_scan):
    r = ingest(ws, [pdf], read_scan=fake_scan(qty_options=["812,45", "872,45"]))
    q = r["issues"][0]
    assert (q["field"], q["kind"], q["number"], q["status"]) == ("qty", "mismatch", "ЗР/ВГ/1", "open")
    assert r["open_issues"] == 1 and r["added"] == ["ЗР/ВГ/1"]
    a = show(ws, "ЗР/ВГ/1")["act"]
    assert a["qty"] == "812,45" and [i["id"] for i in a["issues"]] == [q["id"]]


def test_resolve_by_option_is_remembered(ws, pdf, fake_scan):
    scan = fake_scan(qty_options=["812,45", "872,45"])
    q = ingest(ws, [pdf], read_scan=scan)["issues"][0]["id"]
    r = resolve(ws, q, "2")
    assert (r["value"], r["field"], r["number"]) == ("872,45", "qty", "ЗР/ВГ/1") and issues(ws)["open"] == 0
    r = ingest(ws, [pdf], read_scan=scan)
    assert r["issues"] == [] and issues(ws)["open"] == 0
    assert show(ws, "ЗР/ВГ/1")["act"]["qty"] == "872,45"


def test_resolve_by_free_text(ws, pdf, fake_scan):
    q = ingest(ws, [pdf], read_scan=fake_scan(appendix_options=["Акт №СТЛ/1/ФМС - 1 лист;", "Акт №ССТЛ 1/ФМС - 1 лист;"]))["issues"][0]["id"]
    resolve(ws, q, "Акт отбора проб №СТЛ/1/ФМС/12.08 от 12.08.2024 г. - 1 лист;")
    assert show(ws, "ЗР/ВГ/1")["act"]["appendices"] == ["Акт отбора проб №СТЛ/1/ФМС/12.08 от 12.08.2024 г. - 1 лист;"]


def test_same_question_is_not_asked_twice_while_open(ws, pdf, fake_scan):
    scan = fake_scan(qty_options=["812,45", "872,45"])
    ingest(ws, [pdf], read_scan=scan)
    assert ingest(ws, [pdf], read_scan=scan)["issues"] == [] and issues(ws)["open"] == 1


def test_conflict_keeps_old_until_answered(ws, pdf, fake_scan):
    ingest(ws, [pdf], read_scan=fake_scan(qty="812,45"))
    r = ingest(ws, [pdf], read_scan=fake_scan(qty="1000"))
    q = r["issues"][0]
    assert (q["kind"], q["options"], r["updated"]) == ("conflict", ["заменить", "оставить"], [])
    assert "qty" in q["fragments"][0]
    assert show(ws, "ЗР/ВГ/1")["act"]["qty"] == "812,45"
    resolve(ws, q["id"], "1")
    assert show(ws, "ЗР/ВГ/1")["act"]["qty"] == "1000" and issues(ws)["open"] == 0


def test_conflict_keep_old(ws, pdf, fake_scan):
    ingest(ws, [pdf], read_scan=fake_scan(qty="812,45"))
    q = ingest(ws, [pdf], read_scan=fake_scan(qty="1000"))["issues"][0]["id"]
    assert code_of(lambda: resolve(ws, q, "может быть")) == "bad_value"
    resolve(ws, q, "2")
    assert show(ws, "ЗР/ВГ/1")["act"]["qty"] == "812,45" and issues(ws)["open"] == 0


def test_identical_scan_is_not_a_conflict(ws, pdf, fake_scan):
    ingest(ws, [pdf], read_scan=fake_scan())
    r = ingest(ws, [pdf], read_scan=fake_scan())
    assert r["issues"] == [] and r["updated"] == ["ЗР/ВГ/1"]


def test_undo_restores_open_issues(ws, pdf, fake_scan):
    q = ingest(ws, [pdf], read_scan=fake_scan(qty_options=["1", "2"]))["issues"][0]["id"]
    resolve(ws, q, "2")
    assert undo(ws)["undone"].startswith("ответ на вопрос") and issues(ws)["open"] == 1
    assert show(ws, "ЗР/ВГ/1")["act"]["qty"] == "1"


def test_unknown_issue_and_delete_drops_issues(ws, pdf, fake_scan):
    ingest(ws, [pdf], read_scan=fake_scan(qty_options=["1", "2"]))
    assert code_of(lambda: resolve(ws, "q99", "1")) == "issue_not_found"
    delete(ws, "ЗР/ВГ/1")
    assert issues(ws) == {"issues": [], "open": 0} and summary(ws)["total"] == 0
