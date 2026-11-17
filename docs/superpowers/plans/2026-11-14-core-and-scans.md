# Ядро реестра и разбор сканов — план работ (этапы 0–2)

> Исторический документ: написан в ходе работы на документах реального объекта, которых в репозитории нет.
> Номера актов, объёмы и названия обезличены; счётчики вроде «63 акта» относятся к тем документам,
> а не к синтетическим примерам из `examples/`.

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Проверить, годится ли pi с локальной моделью, и собрать ядро: команды с ответом в JSON, которые разбирают акты (xlsx и сканы PDF) и ведут накопительный реестр с историей, правками и спорными местами.

**Architecture:** Детерминированная библиотека на Python поверх черновика от 14.11 (`aosr/model.py`, `parse_xlsx.py`, `registry.py`). Рабочая папка хранит реестр, историю версий и состояние (вопросы, ручные правки). Сканы читают две модели со зрением, расхождения становятся вопросами. Единственная граница для будущего бота — команды `python -m aosr … ` с JSON на выходе.

**Tech Stack:** Python 3.12+, openpyxl, PyMuPDF (рендер PDF), pytest, urllib из стандартной библиотеки (вызов хаба). Проба: Node 22+, `@earendil-works/pi-coding-agent` (версия фиксируется точно).

**Spec:** `docs/superpowers/specs/2026-11-14-reestr-agent-design.md`

**Вне этого плана:** бот и агент (этапы 3–4). Их план пишется после задачи 1, когда известен исход пробы.

## Global Constraints

- Модели только через `https://api.neuraldeep.ru/v1`. Сканы: основная `qwen3.6-fp8-noreason`, вторая `qwen3.8-27b-noreason`. Диалог (проба): `qwen3.8-27b`.
- Ключ хаба берётся из переменной `NEURALDEEP_API_KEY`, иначе запуском команды из `NEURALDEEP_KEY_CMD` (по умолчанию `~/.local/bin/neuraldeep-hub-key`). В файлы и логи ключ не пишется.
- Модель не пишет в реестр: она только переписывает текст со скана; коды, количество, единицу и место выделяет `aosr.model.parse_item` / `parse_place`.
- Лист реестра — «общий», данные с 5-й строки, колонки: D № по ведомости, E название документа, F работы / приложения, G дата (текст `19.02.2025г.`), H номер, I единица, J количество, K место. Колонки A–C и L–P ведёт человек, они сохраняются.
- Несколько работ акта пишутся в одну ячейку через `\n`. Дубль определяется по номеру акта (`norm_number`).
- Любая непустая строка реестра сохраняется по значениям; оформление строк данных приводится к единому.
- Каждая команда отвечает одним JSON-объектом в stdout: `{"ok": true, …}` либо `{"ok": false, "error": {"code": "…", "message": "…"}}` с кодом выхода 1. Сообщения по-русски.
- `input/` и `out/` в git не попадают (там документы заказчика).

## Review Focus

Чего проект прямо не описывает, но что встретится в работе:

1. **В книге есть листы, не похожие на акт, или дата акта записана текстом** (`19.02.2025`). Ожидание: лист пропущен с записью в `notes`, текстовая дата разобрана; падения нет. → задача 2.
2. **В одной загрузке два акта с одним номером.** Ожидание: в реестр идёт последний, в `notes` запись о дубле с обоими источниками. → задача 5.
3. **Прислан не тот файл**: не xlsx/pdf, битый архив, PDF с нулём страниц или с одной страницей. Ожидание: ошибка `bad_file` по этому файлу в `errors`, остальные файлы обработаны, реестр не тронут этим файлом. → задачи 5 и 8.
4. **Модель ответила мусором или недоступна.** Ожидание: одна модель упала — акт принят по второй с пометкой «проверено одной моделью»; упали обе — ошибка `model_error` по файлу. → задача 9.
5. **`undo` без истории и команда по номеру, которого нет.** Ожидание: `nothing_to_undo` и `act_not_found`, реестр не меняется. → задачи 4 и 5.

---

## Структура файлов

| Файл | Ответственность |
|---|---|
| `aosr/model.py` (есть) | `Act`, `WorkItem`, разбор строк работ и места; + сериализация |
| `aosr/parse_xlsx.py` (есть) | книга xlsx → `list[Act]` |
| `aosr/registry.py` (есть) | чтение/запись блоков листа «общий» |
| `aosr/errors.py` | `AosrError(code, message)` |
| `aosr/store.py` | рабочая папка: реестр, история, состояние |
| `aosr/ops.py` | операции: ingest, find, show, set, delete, resolve, undo, replace, export, summary |
| `aosr/llm.py` | единственное место вызова моделей |
| `aosr/scan.py` | PDF → страницы → переписанный акт |
| `aosr/compare.py` | нормализация и сравнение двух прочтений |
| `aosr/__main__.py` | разбор аргументов, JSON в stdout (заменяет `aosr/cli.py`) |
| `spikes/2026-11-pi/` | проба pi, одноразовый код |

---

### Task 1: Проба pi с локальной моделью (одноразовый код, без тестов)

**Files:**
- Create: `spikes/2026-11-pi/package.json`, `spikes/2026-11-pi/agent-home/models.json`, `spikes/2026-11-pi/probe.ts`, `spikes/2026-11-pi/RESULT.md`

**Interfaces:**
- Produces: `RESULT.md` с выводом «pi годится / не годится» и точными именами опций SDK, которые использует план этапа 3.

- [ ] **Step 1: Поставить pi с точной версией.** `npm init -y`, затем `npm install --save-exact @earendil-works/pi-coding-agent tsx`. Записать версию в `RESULT.md`.

- [ ] **Step 2: Подключить хаб.** В `agent-home/models.json` провайдер `neuraldeep`: `baseUrl` `https://api.neuraldeep.ru/v1`, `api` `openai-completions`, `apiKey` `!~/.local/bin/neuraldeep-hub-key`, `compat.supportsDeveloperRole: false`, модели `qwen3.8-27b` и `qwen3.6-fp8` с `input: ["text","image"]`, `contextWindow: 256000`. Найти в документации (`docs.pi.dev/latest/configuration.md`, `sdk.md`), как указать SDK каталог агента `agent-home` вместо `~/.pi/agent`, и использовать его.

- [ ] **Step 3: Написать `probe.ts`.** Сессия `createAgentSession` с: встроенными инструментами выключенными, двумя своими инструментами-заглушками, сессией в памяти, системной подсказкой «Ты помощник по реестру актов. Используй инструменты, не выдумывай данные, отвечай по-русски кратко». Заглушки: `find_acts({number?, text?, date_from?, date_to?})` возвращает два придуманных акта; `delete_act({number})` возвращает `{"status":"needs_confirmation"}`. Скрипт печатает по каждой реплике: вызванные инструменты с аргументами и итоговый текст.

- [ ] **Step 4: Прогнать 5 реплик по 3 раза** (новая сессия на каждый прогон):

| Реплика | Ожидание |
|---|---|
| «Какие акты были в августе 2024?» | `find_acts` с `date_from` 2024-08-01 и `date_to` 2024-08-31 |
| «Найди акт ВО/11-15/БО» | `find_acts` с `number` «ВО/11-15/БО» |
| «Удали акт ВО/11-15/БО» | `delete_act` с этим номером; в ответе просьба подтвердить, без слов «удалён» |
| «Привет, что ты умеешь?» | инструменты не вызваны |
| «Есть акты по обратной засыпке?» | `find_acts` с `text`, содержащим «засыпк» |

- [ ] **Step 5: Проверить то, на что опирается этап 3**, и записать в `RESULT.md` точные имена опций и поведение: (а) встроенные `bash/read/write/edit/grep/find/ls` недоступны модели — попросить «выполни ls» и убедиться, что вызова нет; (б) как передаются свои инструменты — опцией или расширением; (в) как отключить автозагрузку расширений, навыков и файлов контекста из рабочей папки; (г) как сохранить сессию на диск и продолжить её после перезапуска процесса; (д) как подать в сессию служебное сообщение не от пользователя.

- [ ] **Step 6: Записать вывод.** Критерий «годится»: не менее 14 из 15 прогонов с ожидаемым инструментом и аргументами и пункты (а)–(г) выполнимы. Если нет — повторить шаг 4 с `qwen3.6-fp8`, записать оба результата.

- [ ] **Step 7: Остановиться и показать `RESULT.md` Алексею.** Решение «pi или запасной путь» принимает он. Задачи 2–10 от этого решения не зависят и могут идти параллельно.

---

### Task 2: Основа проекта и устойчивый разбор xlsx

**Files:**
- Create: `pyproject.toml`, `.gitignore`, `aosr/errors.py`, `tests/test_model.py`, `tests/test_parse_xlsx.py`, `tests/conftest.py`
- Modify: `aosr/model.py`, `aosr/parse_xlsx.py`
- Delete: `tests/test_core.py` (тесты переезжают в файлы по модулям без изменения утверждений)

**Interfaces:**
- Produces:
  - `aosr.errors.AosrError(code: str, message: str)`
  - `Act.origin: str` — `"xlsx"` или `"scan"`; `Act.to_dict() -> dict`, `Act.from_dict(d) -> Act` (даты в ISO)
  - `parse_workbook(path) -> tuple[list[Act], list[str]]` — второе значение: записи о пропущенных листах
  - фикстуры pytest: `acts_xlsx`, `template_xlsx` (пути в `input/`, пропуск теста при отсутствии), `make_act(number, date, **kw) -> Act`

- [ ] **Step 1: Основа.** `git init`; `.gitignore`: `input/`, `out/`, `.venv/`, `__pycache__/`, `node_modules/`, `*.report.txt`. `pyproject.toml`: пакет `aosr`, зависимости `openpyxl`, `pymupdf`; dev — `pytest`. `python3 -m venv .venv && .venv/bin/pip install -e '.[dev]'`.

- [ ] **Step 2: Перенести существующие тесты** в `tests/test_model.py` и `tests/test_parse_xlsx.py`, запустить `.venv/bin/pytest -q`. Ожидание: все прежние утверждения про `parse_item`, `parse_place` и 63 акта проходят.

- [ ] **Step 3: Написать падающие тесты.**

```python
def test_act_roundtrip(make_act):
    a = make_act("ВО/1", date(2025, 2, 19), items=[WorkItem("5.3.1.31", "Укладка", "87,5", "м")], appendices=["Схема - 1 лист;"])
    assert Act.from_dict(a.to_dict()) == a

def test_text_date_is_parsed(tmp_path, acts_xlsx):
    # копия книги, где на первом листе дата акта заменена строкой "19.02.2025"
    acts, _ = parse_workbook(book_with_text_date(tmp_path, acts_xlsx))
    assert acts[0].date == date(2025, 2, 19) and "не найдена дата акта" not in acts[0].warnings

def test_non_act_sheets_are_reported(tmp_path, acts_xlsx):
    # копия книги с добавленным листом «Справка» без акта
    acts, skipped = parse_workbook(book_with_extra_sheet(tmp_path, acts_xlsx))
    assert len(acts) == 63 and skipped == ["лист «Справка» не похож на акт"]

def test_not_a_workbook(tmp_path):
    p = tmp_path / "x.xlsx"; p.write_text("не архив")
    with pytest.raises(AosrError) as e: parse_workbook(p)
    assert e.value.code == "bad_file"
```

- [ ] **Step 4: Запустить, убедиться что падают.** `.venv/bin/pytest tests/test_model.py tests/test_parse_xlsx.py -q`

- [ ] **Step 5: Реализовать.** `Act.origin` со значением по умолчанию `"xlsx"`; `to_dict`/`from_dict`; в `parse_xlsx._d` принять строку `ДД.ММ.ГГГГ`; `parse_workbook` возвращает пару и оборачивает ошибку открытия в `AosrError("bad_file", …)`.

- [ ] **Step 6: Запустить всё, зафиксировать.** `.venv/bin/pytest -q` → всё проходит. `git add -A && git commit -m "chore: project scaffold, robust xlsx parsing"`

---

### Task 3: Реестр не теряет чужие строки

**Files:**
- Modify: `aosr/registry.py`
- Test: `tests/test_registry.py`

**Interfaces:**
- Consumes: `Act`, `clean_number`, `norm_number` из `aosr.model`.
- Produces:
  - `Block(cells: dict[int, object], tail: list[dict[int, object]])`; свойство `appendices: list[str]` (чтение — строки хвоста, где заполнена только колонка F; запись — заменяет эти строки, прочие строки хвоста остаются после них); `key`, `date` как сейчас.
  - `load(path) -> list[Block]`; `save(path, blocks: list[Block], out) -> None` — читает книгу `path`, пишет блоки, сохраняет в `out`.
  - `init_registry(template, out) -> None` — копия шаблона с очищенной областью данных (A–P от строки 5 до строки «Сдал:»), включая пример.
  - `act_cells(act) -> dict[int, object]`, `sort_blocks(blocks) -> list[Block]` (по дате, затем по ключу; блоки без даты — в конец в исходном порядке).
  - `is_registry(path) -> bool` — в книге есть лист «общий», в 4-й строке которого есть ячейка «Наименование документа».
  - константы `FIELD_COLS = {"code": 4, "work": 6, "date": 7, "number": 8, "unit": 9, "qty": 10, "place": 11}`.
- Удаляется: `merge_acts`, `update_registry`, `Result` (их роль переходит в `ops.ingest`).

- [ ] **Step 1: Написать падающие тесты.**

```python
def test_init_clears_template(tmp_path, template_xlsx):
    out = tmp_path / "r.xlsx"; init_registry(template_xlsx, out)
    assert load(out) == [] and is_registry(out)

def test_foreign_rows_survive(tmp_path, template_xlsx, make_act):
    out = tmp_path / "r.xlsx"; init_registry(template_xlsx, out)
    foreign = Block(cells={5: "Общий журнал работ", 8: "ОЖР-1", 12: "01.07.2024г."},
                    tail=[{6: "Том 1 - 96 листов"}, {6: "примечание", 14: "ООО «Ромашка»"}])
    ours = Block(cells=act_cells(make_act("ВО/1", date(2024, 7, 11))), tail=[{6: "Схема - 1 лист;"}])
    save(out, sort_blocks([foreign, ours]), out)
    got = {b.key: b for b in load(out)}
    assert got["ОЖР-1"].cells[12] == "01.07.2024г."
    assert got["ОЖР-1"].tail == foreign.tail            # строка с двумя колонками не потеряна
    assert got["ОЖР-1"].appendices == ["Том 1 - 96 листов"]
    assert [b.key for b in load(out)] == ["ВО/1", "ОЖР-1"]  # без даты — в конец

def test_setting_appendices_keeps_other_tail_rows():
    b = Block(cells={8: "X"}, tail=[{6: "a"}, {6: "note", 14: "org"}, {6: "b"}])
    b.appendices = ["c"]
    assert b.tail == [{6: "c"}, {6: "note", 14: "org"}]

def test_is_registry(acts_xlsx, template_xlsx):
    assert is_registry(template_xlsx) and not is_registry(acts_xlsx)
```

Перенести из прежних тестов без изменения смысла: сдвиг подписей «Сдал/Принял» при переполнении (201 блок по 10 строк) и сохранение ручной колонки O.

- [ ] **Step 2: Запустить, убедиться что падают.** `.venv/bin/pytest tests/test_registry.py -q`

- [ ] **Step 3: Реализовать** по блоку Interfaces. Строки до первого блока с номером собираются в ведущий блок с пустыми `cells` и ключом `""`; `sort_blocks` оставляет его первым. Очистка остатков шаблона остаётся только в `init_registry`; `save` стирает и переписывает область данных целиком из переданных блоков.

- [ ] **Step 4: Запустить всё, зафиксировать.** `git commit -m "feat: registry preserves foreign rows, init from template"`

---

### Task 4: Рабочая папка, состояние и история

**Files:**
- Create: `aosr/store.py`
- Test: `tests/test_store.py`

**Interfaces:**
- Consumes: `init_registry`, `AosrError`.
- Produces:
  - `Issue` (dataclass): `id: str` (`"q1"`, `"q2"`…), `number: str`, `kind: str` (`"mismatch"` | `"conflict"`), `field: str`, `options: list`, `fragments: list[str]`, `status: str` (`"open"` | `"resolved"`), `chosen: str | None`
  - `State` (dataclass): `issues: list[Issue]`, `overrides: dict[str, dict[str, object]]` (ключ акта → поле → значение), `pending: dict[str, dict]` (id вопроса → `Act.to_dict()`), `next_issue: int`; метод `new_issue(**kw) -> Issue`
  - `Workspace(home: Path)`: свойства `registry_path` (`home/registry.xlsx`), `inbox` (`home/inbox/`); `init(template) -> None` (ошибка `already_initialized`, если реестр есть); `require() -> None` (ошибка `no_registry`); `load_state() -> State`; `save_state(state) -> None` (запись через временный файл и переименование); `snapshot(label: str) -> None`; `undo() -> str` (возвращает `label` отменённого изменения; ошибка `nothing_to_undo`); `history() -> list[str]`
  - История: `home/history/NNNN/{registry.xlsx,state.json,label.txt}`, хранится не больше 50 последних.

- [ ] **Step 1: Написать падающие тесты.**

```python
def test_undo_restores_registry_and_state(ws):          # ws — фикстура: Workspace в tmp_path после init
    before = ws.registry_path.read_bytes()
    ws.snapshot("добавлены акты")
    ws.registry_path.write_bytes(b"changed")
    st = ws.load_state(); st.new_issue(number="ВО/1", kind="mismatch", field="qty", options=["1", "2"], fragments=[]); ws.save_state(st)
    assert ws.undo() == "добавлены акты"
    assert ws.registry_path.read_bytes() == before and ws.load_state().issues == []

def test_undo_without_history(ws):
    with pytest.raises(AosrError) as e: ws.undo()
    assert e.value.code == "nothing_to_undo"

def test_history_is_capped(ws):
    for i in range(55): ws.snapshot(f"шаг {i}")
    assert len(ws.history()) == 50 and ws.history()[-1] == "шаг 54"

def test_issue_ids_are_sequential_and_survive_reload(ws):
    st = ws.load_state(); a = st.new_issue(number="x", kind="mismatch", field="qty", options=[], fragments=[]); ws.save_state(st)
    st = ws.load_state(); b = st.new_issue(number="y", kind="mismatch", field="qty", options=[], fragments=[])
    assert (a.id, b.id) == ("q1", "q2")

def test_commands_require_registry(tmp_path):
    with pytest.raises(AosrError) as e: Workspace(tmp_path).require()
    assert e.value.code == "no_registry"
```

- [ ] **Step 2–4:** запустить (падают) → реализовать → `.venv/bin/pytest -q` проходит → `git commit -m "feat: workspace with history and state"`

---

### Task 5: Операции с реестром и команды с JSON

**Files:**
- Create: `aosr/ops.py`, `aosr/__main__.py`
- Delete: `aosr/cli.py`, `aosr/report.py`
- Test: `tests/test_ops.py`, `tests/test_cli.py`

**Interfaces:**
- Consumes: `Workspace`, `State`, `registry.load/save/sort_blocks/act_cells/FIELD_COLS/is_registry`, `parse_workbook`.
- Produces (все функции принимают `ws: Workspace` первым аргументом и возвращают `dict` без ключа `ok`):
  - `ingest(ws, files: list[Path], *, read_scan=None) -> dict` — ключи: `added: list[str]`, `updated: list[str]`, `total: int`, `issues: list[dict]` (новые открытые вопросы), `open_issues: int`, `notes: list[{"number","text"}]`, `errors: list[{"file","code","message"}]`, `registry: str`. Файл `.xlsx`, для которого `is_registry` истинно, даёт ошибку `bad_file` с текстом «это реестр, а не книга с актами». Файлы `.pdf` передаются в `read_scan(path) -> tuple[Act, list[dict], list[str]]` (акт, заготовки вопросов, заметки); при `read_scan=None` — ошибка `bad_file`. Если реестр изменился — один `snapshot` на вызов, с подписью вида «загрузка: 3 файла, добавлено 12».
  - `find(ws, *, number=None, text=None, date_from=None, date_to=None) -> {"acts": [summary], "count": int}`; `summary`: `number`, `date` (ISO), `work` (первые 120 знаков), `place`, `appendices` (число), `open_issues` (число). `number` и `text` ищутся без учёта регистра как подстрока.
  - `show(ws, number) -> {"act": {number, date, code, work, unit, qty, place, appendices: list[str], manual: {колонка: значение}, issues: [dict]}}`
  - `set_field(ws, number, field, value) -> {"number", "field", "old", "new"}` — поля: ключи `FIELD_COLS` и `appendix.N` (N с 1; `N = число приложений + 1` добавляет строку). Значение `date` принимается как `ДД.ММ.ГГГГ` и пишется как `ДД.ММ.ГГГГг.`. Запоминается в `state.overrides`. Смена `number` переносит правки и вопросы на новый ключ.
  - `delete(ws, number) -> {"number", "removed_rows": int}` — убирает и правки, и вопросы этого акта.
  - `summary(ws) -> {"total", "date_from", "date_to", "open_issues", "history": int}`
  - `export(ws) -> {"registry": str, "open_issues": int, "issues_by_act": {номер: число}}`
  - `undo(ws) -> {"undone": str}`
  - Ошибки: `act_not_found`; `ambiguous_number` (точного совпадения нет, подстрока подходит нескольким — в сообщении список); `bad_field`; `bad_value`.
- Команды: `python -m aosr --home DIR <init --template F | ingest F… | find [--number --text --from --to] | show N | set N FIELD VALUE | delete N | summary | export | undo>`.

Порядок внутри `ingest` для каждого акта: разобрать → наложить правки из `state.overrides` → вписать в блок (новый или существующий по ключу) → `sort_blocks` → `save`. Предупреждения акта (`Act.warnings`) уходят в `notes`.

- [ ] **Step 1: Написать падающие тесты.**

```python
def test_ingest_real_book(ws, acts_xlsx):
    r = ingest(ws, [acts_xlsx])
    assert (len(r["added"]), r["updated"], r["total"], r["errors"]) == (63, [], 63, [])
    assert len(r["notes"]) == 22                     # место взято после слова «колодцев»
    dates = [a["date"] for a in find(ws)["acts"]]
    assert dates == sorted(dates) and dates[0] == "2024-07-11"

def test_reingest_updates_without_duplicates(ws, acts_xlsx):
    ingest(ws, [acts_xlsx]); r = ingest(ws, [acts_xlsx])
    assert (r["added"], len(r["updated"]), r["total"]) == ([], 63, 63)

def test_manual_fix_survives_reingest(ws, acts_xlsx):
    ingest(ws, [acts_xlsx])
    set_field(ws, "ВО/11-15/БО", "place", "колодцы 11-15")
    ingest(ws, [acts_xlsx])
    assert show(ws, "ВО/11-15/БО")["act"]["place"] == "колодцы 11-15"

def test_manual_columns_survive(ws, acts_xlsx):          # человек вписал «Реестр №» в колонку O в Excel
    ingest(ws, [acts_xlsx]); write_cell(ws.registry_path, number="ВО/11-15/РГ", col=15, value="Реестр 7")
    ingest(ws, [acts_xlsx])
    assert show(ws, "ВО/11-15/РГ")["act"]["manual"] == {"O": "Реестр 7"}

def test_example_from_spec(ws, acts_xlsx):
    ingest(ws, [acts_xlsx]); a = show(ws, "ВО/21-31/МТ")["act"]
    assert (a["code"], a["unit"], a["qty"], a["date"]) == ("5.3.1.31\n5.3.1.32", "м\nшт", "87,5\n12", "2025-02-19")
    assert a["place"] == "ДК21 - 7, ДК23 - 8, ДК25 - 9" and len(a["appendices"]) == 7

def test_delete_and_undo(ws, acts_xlsx):
    ingest(ws, [acts_xlsx]); delete(ws, "ВО/11-15/БО")
    assert summary(ws)["total"] == 62
    assert undo(ws)["undone"].startswith("удалён акт") and summary(ws)["total"] == 63

def test_unknown_and_ambiguous_number(ws, acts_xlsx):
    ingest(ws, [acts_xlsx])
    assert code_of(lambda: show(ws, "НЕТ/0")) == "act_not_found"
    assert code_of(lambda: show(ws, "ВО/11-15")) == "ambiguous_number"
    assert summary(ws)["total"] == 63

def test_duplicate_number_in_one_upload(ws, tmp_path, acts_xlsx):
    r = ingest(ws, [book_with_duplicated_first_sheet(tmp_path, acts_xlsx)])
    assert r["total"] == 63 and any("дважды" in n["text"] for n in r["notes"])

def test_bad_file_does_not_block_others(ws, tmp_path, acts_xlsx, template_xlsx):
    junk = tmp_path / "x.docx"; junk.write_text("?")
    r = ingest(ws, [junk, template_xlsx, acts_xlsx])
    assert [e["code"] for e in r["errors"]] == ["bad_file", "bad_file"] and r["total"] == 63

def test_set_validation(ws, acts_xlsx):
    ingest(ws, [acts_xlsx])
    assert code_of(lambda: set_field(ws, "ВО/11-15/БО", "color", "x")) == "bad_field"
    assert code_of(lambda: set_field(ws, "ВО/11-15/БО", "date", "вчера")) == "bad_value"
    assert set_field(ws, "ВО/11-15/БО", "date", "20.07.2024")["new"] == "20.07.2024г."
```

`tests/test_cli.py` — через `subprocess`:

```python
def test_cli_json_contract(tmp_path, template_xlsx, acts_xlsx):
    assert run(tmp_path, "init", "--template", template_xlsx) == (0, {"ok": True})
    code, out = run(tmp_path, "ingest", acts_xlsx); assert code == 0 and out["ok"] and out["total"] == 63
    code, out = run(tmp_path, "show", "НЕТ/0")
    assert code == 1 and out == {"ok": False, "error": {"code": "act_not_found", "message": ANY_STR}}
    code, out = run(tmp_path / "empty", "summary"); assert out["error"]["code"] == "no_registry"
```

- [ ] **Step 2–4:** запустить (падают) → реализовать → `.venv/bin/pytest -q` проходит → `git commit -m "feat: registry operations and JSON CLI"`

---

### Task 6: Спорные места и приём реестра от инженера

**Files:**
- Modify: `aosr/ops.py`, `aosr/__main__.py`
- Test: `tests/test_issues.py`, `tests/test_replace.py`

**Interfaces:**
- Consumes: `State.new_issue`, `set_field`, `registry.load`.
- Produces:
  - `issues(ws, *, number=None) -> {"issues": [dict], "open": int}` — открытые вопросы.
  - `resolve(ws, issue_id, answer: str) -> {"issue", "number", "field", "value"}`.
    Вопрос `mismatch`: ответ `"1"`/`"2"` берёт соответствующий вариант, любой другой текст — значение как есть; результат применяется через `set_field` (то есть запоминается как ручная правка). Для полей `items` и `appendices` допустимы только `"1"`/`"2"`.
    Вопрос `conflict`: `"1"` — заменить акт отложенным из `state.pending`, `"2"` — оставить прежний; в обоих случаях отложенный акт удаляется.
    Ошибки: `issue_not_found`, `bad_value`.
  - `replace_registry(ws, file, *, missing: str = "check") -> dict`. `"check"` ничего не меняет и возвращает `{"missing": [номера актов, которые есть в текущем реестре и отсутствуют в файле], "incoming_total": int}`. `"keep"` — файл становится текущим, недостающие акты добавляются в него. `"drop"` — файл становится текущим как есть. Файл, не прошедший `is_registry`, — ошибка `bad_file`. Правки и вопросы по актам, которых не стало, удаляются.
  - `ingest` принимает от `read_scan` заготовки вопросов (`{"kind","field","options","fragments"}`) и регистрирует их через `State.new_issue`; для `kind == "conflict"` кладёт акт в `state.pending`, а реестр по этому акту не меняет.
- Команды: `issues [--number N]`, `resolve Q ANSWER`, `replace-registry FILE [--missing check|keep|drop]`.

- [ ] **Step 1: Написать падающие тесты.** Вопросы создаются поддельным `read_scan`, который возвращает заранее заданные акт и заготовки.

```python
def test_mismatch_goes_to_registry_with_primary_value(ws, fake_scan):
    r = ingest(ws, [PDF], read_scan=fake_scan(qty_options=["812,45", "872,45"]))
    assert r["issues"][0]["field"] == "qty" and r["open_issues"] == 1
    assert show(ws, "ЗР/ВГ/1")["act"]["qty"] == "812,45"          # значение основной модели уже в реестре

def test_resolve_by_option_and_by_text(ws, fake_scan):
    q = ingest(ws, [PDF], read_scan=fake_scan(qty_options=["812,45", "872,45"]))["issues"][0]["id"]
    assert resolve(ws, q, "2")["value"] == "872,45" and issues(ws)["open"] == 0
    ingest(ws, [PDF], read_scan=fake_scan(qty_options=["812,45", "872,45"]))   # повторная загрузка
    assert show(ws, "ЗР/ВГ/1")["act"]["qty"] == "872,45" and issues(ws)["open"] == 0   # ответ запомнен, вопрос не возвращается

def test_conflict_keeps_old_until_answered(ws, fake_scan):
    ingest(ws, [PDF], read_scan=fake_scan(qty="812,45"))
    r = ingest(ws, [PDF], read_scan=fake_scan(qty="1000"))
    assert r["issues"][0]["kind"] == "conflict" and show(ws, "ЗР/ВГ/1")["act"]["qty"] == "812,45"
    resolve(ws, r["issues"][0]["id"], "1")
    assert show(ws, "ЗР/ВГ/1")["act"]["qty"] == "1000"

def test_undo_restores_open_issues(ws, fake_scan):
    q = ingest(ws, [PDF], read_scan=fake_scan(qty_options=["1", "2"]))["issues"][0]["id"]
    resolve(ws, q, "2"); undo(ws)
    assert issues(ws)["open"] == 1

def test_replace_registry_detects_lost_acts(ws, acts_xlsx, tmp_path):
    ingest(ws, [acts_xlsx]); old = copy_registry(ws, tmp_path)          # копия, которую инженер «скачал»
    delete(ws, "ВО/11-15/БО"); undo(ws)                                 # реестр снова полный
    remove_act_from_file(old, "ВО/11-15/РГ")                            # в его копии акта нет
    assert replace_registry(ws, old)["missing"] == ["ВО/11-15/РГ"] and summary(ws)["total"] == 63
    replace_registry(ws, old, missing="keep"); assert summary(ws)["total"] == 63
    replace_registry(ws, old, missing="drop"); assert summary(ws)["total"] == 62

def test_replace_rejects_acts_book(ws, acts_xlsx):
    assert code_of(lambda: replace_registry(ws, acts_xlsx)) == "bad_file"
```

- [ ] **Step 2–4:** запустить (падают) → реализовать → `.venv/bin/pytest -q` проходит → `git commit -m "feat: issues, resolve, replace-registry"`

---

### Task 7: Вызов моделей в одном месте

**Files:**
- Create: `aosr/llm.py`
- Test: `tests/test_llm.py`

**Interfaces:**
- Produces:
  - `chat_json(model: str, prompt: str, images: list[bytes], *, transport=None, timeout: int = 240) -> dict` — запрос к `/chat/completions` (`temperature` 0, `max_tokens` 4000, изображения как `image_url` с `data:image/jpeg;base64,…`), возвращает разобранный JSON из ответа. Обёртку ```` ```json … ``` ```` снимает. Одна повторная попытка при сетевой ошибке или ответе 5xx.
  - `transport(url: str, headers: dict, body: dict, timeout: int) -> dict` — подменяется в тестах; настоящий делает POST через `urllib`.
  - Ошибки: `AosrError("model_error", …)` — сеть, не-200, пустой ответ, ответ не JSON-объект. Ключ в текст ошибки не попадает.
  - `api_key() -> str` по правилу из Global Constraints.

- [ ] **Step 1: Написать падающие тесты** с поддельным `transport`: ответ в ограждении ```` ```json ```` разбирается; ответ «Извините, не могу» даёт `model_error`; первая попытка бросает `URLError`, вторая успешна — результат получен, вызовов два; в теле запроса два изображения и `temperature == 0`; при ошибке 401 в сообщении нет значения ключа.

- [ ] **Step 2–4:** запустить (падают) → реализовать → проходит → `git commit -m "feat: single model-call entry point"`

---

### Task 8: Скан PDF → переписанный акт (одна модель)

**Files:**
- Create: `aosr/scan.py`, `tests/fixtures/scan_example/qwen3.6-fp8-noreason.json`, `tests/fixtures/scan_example/qwen3.8-27b-noreason.json`, `scripts/record_scan_fixture.py`
- Test: `tests/test_scan.py`

**Interfaces:**
- Consumes: `chat_json`, `parse_item`, `parse_place`, `clean_number`, `Act`.
- Produces:
  - `render_pages(pdf: Path, pages: int = 2, dpi: int = 200) -> list[bytes]` — JPEG первых страниц. Ошибка `bad_file`: файл не открывается как PDF или страниц нет. Одна страница — не ошибка.
  - `PROMPT: str` — подсказка (ниже, дословно).
  - `transcribe(images: list[bytes], model: str, *, chat=chat_json) -> dict` — ответ модели, проверенный по схеме: строки `номер_акта`, `дата_акта`, `название_работ`; списки строк `работы`, `приложения`; булево `есть_подписи`. Нарушение схемы — `model_error`.
  - `to_act(raw: dict, source: str) -> Act` — `origin="scan"`; номер через `clean_number`; дата из `ДД.ММ.ГГГГ` или «13 августа 2024 г.»; каждая строка `работы` через `parse_item`; место через `parse_place`; у приложений снимается ведущая нумерация («2 Акт отбора…» → «Акт отбора…»). В `warnings`: «из скана — сверь с оригиналом»; при `есть_подписи == False` — «возможно, не весь акт на первых двух страницах»; замечания `parse_item`/`parse_place` как для xlsx.

Подсказка (фиксируется дословно):

```
Перед тобой первые страницы скана акта освидетельствования скрытых работ.
Перепиши из него поля. Верни строго один JSON-объект без пояснений:
{"номер_акта": "", "дата_акта": "ДД.ММ.ГГГГ", "название_работ": "",
 "работы": ["каждая строка пункта 1 целиком, с номером по ведомости и количеством, как в документе"],
 "приложения": ["каждая строка раздела «Приложения» целиком, с числом листов"],
 "есть_подписи": true}
«название_работ» — строка под заголовком «АКТ освидетельствования скрытых работ».
«есть_подписи» — true, если на этих страницах есть блок подписей представителей.
Переписывай цифры, номера и знаки «/» в точности как в документе. Ничего не додумывай и не исправляй.
Если поля нет в документе — пустая строка или пустой список.
```

- [ ] **Step 1: Записать ответы живых моделей.** `scripts/record_scan_fixture.py <pdf> <каталог>` вызывает `render_pages` и `transcribe` для обеих моделей и сохраняет сырые ответы. Запустить на `examples/act_scan.pdf`. Шаг требует сети; тесты после него сети не требуют.

- [ ] **Step 2: Написать падающие тесты.**

```python
def test_to_act_from_recorded_answer(fixture_raw):            # ответ qwen3.6-fp8-noreason из фикстуры
    a = to_act(fixture_raw, "АОСР.pdf")
    assert (a.number, a.date, a.origin) == ("ЗР/ВГ/1", date(2024, 8, 13), "scan")
    assert [(i.code, i.qty, i.unit) for i in a.items] == [
        ("3.2.1.3", "1640,2", "м3"), ("3.2.1.5", "1490,6", "м3"), ("3.2.1.24", "812,45", "м3"),
        ("3.2.1.25", "812,45", "м3"), ("3.2.1.27", "1530,7", "м2")]
    assert a.place == "" and len(a.appendices) == 6          # в названии нет «на участке» — место пустое, с замечанием
    assert not a.appendices[1][0].isdigit()
    assert "из скана — сверь с оригиналом" in a.warnings

def test_russian_month_date():
    assert to_act({**MINIMAL, "дата_акта": "13 августа 2024 г."}, "x").date == date(2024, 8, 13)

def test_no_signatures_is_flagged():
    assert any("не весь акт" in w for w in to_act({**MINIMAL, "есть_подписи": False}, "x").warnings)

def test_schema_violation_is_model_error():
    with pytest.raises(AosrError) as e: transcribe([b"x"], "m", chat=lambda *a, **k: {"номер_акта": 5})
    assert e.value.code == "model_error"

def test_render_real_pdf(scan_pdf):                           # пропуск, если файла нет
    pages = render_pages(scan_pdf); assert len(pages) == 2 and pages[0][:2] == b"\xff\xd8"

def test_render_rejects_non_pdf(tmp_path):
    p = tmp_path / "x.pdf"; p.write_text("не pdf")
    with pytest.raises(AosrError) as e: render_pages(p)
    assert e.value.code == "bad_file"

def test_one_page_pdf_is_accepted(one_page_pdf):
    assert len(render_pages(one_page_pdf)) == 1
```

Если записанный ответ основной модели расходится с ожидаемыми значениями теста по номеру, дате или объёмам — это находка: остановиться и показать Алексею, а не подгонять тест.

- [ ] **Step 3–5:** запустить (падают) → реализовать → проходит → `git commit -m "feat: scan transcription to Act"`

---

### Task 9: Сверка двух моделей и подключение сканов к загрузке

**Files:**
- Create: `aosr/compare.py`
- Modify: `aosr/scan.py`, `aosr/ops.py`, `aosr/__main__.py`
- Test: `tests/test_compare.py`, `tests/test_scan_ingest.py`

**Interfaces:**
- Consumes: `transcribe`, `to_act`, `render_pages`, `act_cells`, `ingest(read_scan=…)`.
- Produces:
  - `normalize(text: str) -> str` — нижний регистр, `ё→е`, все виды кавычек → `"`, все виды тире → `-`, пробелы схлопнуты, пробелы вокруг `/ - , ; : ( ) №` убраны, хвостовые `;` и `.` сняты.
  - `diff_fragments(a: str, b: str, context: int = 3) -> list[str]` — два коротких фрагмента (по одному на вариант): расходящиеся слова и по `context` слов с каждой стороны, с многоточиями.
  - `compare_acts(primary: Act, secondary: Act) -> list[dict]` — заготовки вопросов `{"kind": "mismatch", "field", "options": [a, b], "fragments": [fa, fb]}`. Сравниваются после `normalize`: `number`, `date`, `place`; если число работ разное — один вопрос по полю `items` с вариантами-списками, иначе по ячейкам `code`, `work`, `unit`, `qty` (значения как в `act_cells`); если число приложений разное — один вопрос по полю `appendices`, иначе по `appendix.N` для каждой разошедшейся строки. Для коротких полей (`number`, `date`, `code`, `unit`, `qty`) `fragments` равны `options`.
  - `read_scan(pdf: Path, *, chat=chat_json) -> tuple[Act, list[dict], list[str]]` — рендер, два вызова `transcribe` (модели из Global Constraints), `to_act` для каждого, `compare_acts`. Возвращает акт основной модели. Упала одна модель — акт второй, заметка «проверено одной моделью: <имя упавшей> недоступна», вопросов нет. Упали обе — `AosrError("model_error")`.
  - В `ingest`: если акт из скана уже есть в реестре и его ячейки `act_cells` или приложения отличаются после `normalize` — вместо записи создаётся вопрос `{"kind": "conflict", "field": "act", "options": ["заменить", "оставить"], "fragments": [перечень отличающихся полей]}`. Вопросы `mismatch` по полю, на которое уже есть ручная правка в `state.overrides`, не создаются.
  - `python -m aosr ingest` передаёт `read_scan` по умолчанию; тесты подменяют `chat`.

- [ ] **Step 1: Написать падающие тесты.**

```python
def test_normalize():
    assert normalize("  Акт  отбора проб №СТЛ / 1 /ФМС «12.08» — 1 лист; ") == 'акт отбора проб №стл/1/фмс "12.08"-1 лист'
    assert normalize("Ёмкость") == "емкость"

def test_recorded_answers_disagree_only_where_expected(raw_primary, raw_secondary):
    qs = compare_acts(to_act(raw_primary, "x"), to_act(raw_secondary, "x"))
    assert all(q["field"].startswith("appendix.") for q in qs)        # номер, дата, работы, объёмы совпали
    assert all(len(f) < 120 for q in qs for f in q["fragments"])      # показываем фрагмент, а не строку целиком

def test_cosmetic_differences_are_not_questions(make_act):
    a = make_act("ЗР/ВГ/1", date(2024, 8, 13), appendices=["Набор фотоизображений от 13.08.2024 - 4 листа;"])
    b = make_act("ЗР/ВГ/1", date(2024, 8, 13), appendices=["набор  фотоизображений от 13.08.2024 – 4 листа"])
    assert compare_acts(a, b) == []

def test_qty_mismatch_is_short_question(make_act):
    a = make_act("X", D, items=[WorkItem("3.2.1.24", "Уплотнение", "812,45", "м3")])
    b = make_act("X", D, items=[WorkItem("3.2.1.24", "Уплотнение", "872,45", "м3")])
    assert compare_acts(a, b) == [{"kind": "mismatch", "field": "qty", "options": ["812,45", "872,45"], "fragments": ["812,45", "872,45"]}]

def test_different_item_count_is_one_question(make_act):
    qs = compare_acts(make_act("X", D, items=[I1, I2]), make_act("X", D, items=[I1]))
    assert [q["field"] for q in qs] == ["items"]

def test_one_model_down(scan_pdf, chat_failing_for):
    act, qs, notes = read_scan(scan_pdf, chat=chat_failing_for("qwen3.8-27b-noreason"))
    assert act.number == "ЗР/ВГ/1" and qs == [] and any("проверено одной моделью" in n for n in notes)

def test_both_models_down(scan_pdf, chat_failing_for):
    with pytest.raises(AosrError) as e: read_scan(scan_pdf, chat=chat_failing_for("qwen3.6-fp8-noreason", "qwen3.8-27b-noreason"))
    assert e.value.code == "model_error"

def test_scan_ingest_end_to_end(ws, scan_pdf, acts_xlsx, chat_from_fixtures):
    ingest(ws, [acts_xlsx])
    r = ingest(ws, [scan_pdf], read_scan=lambda p: read_scan(p, chat=chat_from_fixtures))
    assert r["added"] == ["ЗР/ВГ/1"] and r["total"] == 64 and r["errors"] == []
    assert any("из скана" in n["text"] for n in r["notes"])
    assert find(ws, date_from="2024-08-13", date_to="2024-08-13")["acts"][0]["number"] == "ЗР/ВГ/1"

def test_model_error_for_one_file_keeps_others(ws, scan_pdf, acts_xlsx, chat_failing_for):
    r = ingest(ws, [scan_pdf, acts_xlsx], read_scan=lambda p: read_scan(p, chat=chat_failing_for("qwen3.6-fp8-noreason", "qwen3.8-27b-noreason")))
    assert [e["code"] for e in r["errors"]] == ["model_error"] and r["total"] == 63

def test_answered_question_does_not_return(ws, scan_pdf, chat_from_fixtures):
    scan = lambda p: read_scan(p, chat=chat_from_fixtures)
    for q in ingest(ws, [scan_pdf], read_scan=scan)["issues"]: resolve(ws, q["id"], "1")
    assert ingest(ws, [scan_pdf], read_scan=scan)["issues"] == [] and issues(ws)["open"] == 0
```

- [ ] **Step 2–4:** запустить (падают) → реализовать → `.venv/bin/pytest -q` проходит → `git commit -m "feat: two-model scan verification wired into ingest"`

---

### Task 10: Сквозная проверка на живых данных и описание

**Files:**
- Create: `README.md`, `scripts/smoke.sh`
- Modify: `docs/superpowers/specs/2026-11-14-reestr-agent-design.md` (только раздел «Решения, принятые исполнителем» — дописать, что изменилось по ходу)

- [ ] **Step 1: `scripts/smoke.sh`** — во временной папке: `init` из шаблона, `ingest` книги, `ingest` скана (живые модели), `issues`, `resolve` первого вопроса ответом `1`, `set` места у одного акта, `delete` одного акта, `undo`, `export`. Каждая команда печатает свой JSON; скрипт падает при `ok: false`.

- [ ] **Step 2: Запустить и проверить глазами.** `bash scripts/smoke.sh` → итог: 64 акта, удаление отменено. Скопировать итоговый реестр в `out/реестр_проверка.xlsx`, открыть в Excel: шапка и подписи на месте, акт ЗР/ВГ/1 стоит между актами июля и сентября 2024, переносы строк в ячейках читаются, строки приложений под актами.

- [ ] **Step 3: `README.md`** — что это, как поставить, список команд с примером JSON-ответа каждой, устройство рабочей папки, как записать новую фикстуру скана, перечень кодов ошибок.

- [ ] **Step 4: Полный прогон и фиксация.** `.venv/bin/pytest -q` → всё проходит. `git commit -m "docs: README and smoke script"`

- [ ] **Step 5: Показать Алексею** реестр из шага 2 и список открытых вопросов по скану — это вход для плана этапов 3–4.
