"""Операции над реестром. Каждая возвращает словарь для ответа команды; ошибки — AosrError."""
from __future__ import annotations

import re
import shutil
from dataclasses import asdict
from datetime import date
from pathlib import Path
from typing import Callable

from openpyxl.utils import get_column_letter

from .compare import normalize
from .errors import AosrError
from .model import Act, clean_number, norm_number
from .parse_xlsx import parse_workbook
from .registry import (AUTO_COLS, C_NUM, C_PLACE, C_WORK, FIELD_COLS, LAST_COL, Block, act_cells, fmt_date,
                       drop_stray, is_registry, load, save, sort_blocks)
from .store import State, Workspace

ReadScan = Callable[[Path], tuple[Act, list[dict], list[str]]]
_APPENDIX = re.compile(r"^appendix\.(\d+)$")
_DATE = re.compile(r"^(\d{1,2})\.(\d{1,2})\.(\d{4})$")


# ---------- вспомогательное ----------

def _acts(blocks: list[Block]) -> list[Block]:
    """Только акты скрытых работ: другие документы реестра команды не трогают."""
    return [b for b in blocks if b.is_act]


def _locate(blocks: list[Block], number: str, *, partial: bool = False) -> Block:
    """Акт по номеру. Частичное совпадение допустимо только для чтения."""
    key = norm_number(number)
    acts = _acts(blocks)
    exact = [b for b in acts if b.key == key]
    if exact:
        return exact[0]
    if not partial:
        raise AosrError("act_not_found", f"акта с номером «{number}» нет в реестре (для изменения нужен точный номер)")
    partial = [b for b in acts if key and key in b.key]
    if len(partial) == 1:
        return partial[0]
    if partial:
        names = ", ".join(str(b.cells[C_NUM]) for b in partial[:10])
        raise AosrError("ambiguous_number", f"под «{number}» подходит несколько актов: {names}")
    raise AosrError("act_not_found", f"акта «{number}» нет в реестре")


def _src_key(state: State, key: str) -> str:
    """Ключ акта в исходных документах: если номер исправляли вручную, правки хранятся под прежним."""
    for src, ov in state.overrides.items():
        if norm_number(ov.get("number", "")) == key:
            return src
    return key


def _apply_overrides(cells: dict[int, object], appendices: list[str], ov: dict[str, object]) -> None:
    removals = []
    if isinstance(ov.get("appendices"), list):
        appendices[:] = [str(a) for a in ov["appendices"]]
    for name, value in ov.items():
        m = _APPENDIX.match(name)
        if m:
            i = int(m.group(1)) - 1
            if value == "":
                removals.append(i)
            elif i < len(appendices):
                appendices[i] = str(value)
            else:
                appendices.append(str(value))
        elif name in FIELD_COLS:
            col = FIELD_COLS[name]
            if value == "":
                cells.pop(col, None)
            else:
                cells[col] = value
    for i in sorted(removals, reverse=True):
        if i < len(appendices):
            del appendices[i]


def _put(block: Block, cells: dict[int, object], appendices: list[str]) -> None:
    """Обновить в блоке колонки, которые ведёт код; ручные колонки не трогать."""
    for c in AUTO_COLS:
        block.cells.pop(c, None)
    block.cells.update(cells)
    block.appendices = appendices


def _open_by_act(state: State) -> dict[str, int]:
    out: dict[str, int] = {}
    for i in state.open_issues():
        out[i.number] = out.get(i.number, 0) + 1
    return out


def _iso(d: date | None) -> str | None:
    return d.isoformat() if d else None


def _parse_iso(value: str | None, name: str) -> date | None:
    if value is None:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise AosrError("bad_value", f"{name}: ожидается дата ГГГГ-ММ-ДД, получено «{value}»") from None


def _stems(text: str) -> list[str]:
    out = []
    for w in re.findall(r"[0-9a-zа-я/.\-]+", text.lower().replace("ё", "е")):
        if w.isalpha():
            w = w[:-2] if len(w) > 5 else w[:-1] if len(w) > 3 else w
        out.append(w)
    return out


def _haystack(b: Block) -> str:
    parts = [b.cells.get(C_NUM), b.cells.get(C_WORK), b.cells.get(C_PLACE), *b.appendices]
    return " ".join(str(p) for p in parts if p).lower().replace("ё", "е")


def _summary_of(b: Block, open_by_act: dict[str, int]) -> dict:
    number = str(b.cells[C_NUM])
    return {"number": number, "date": _iso(b.date), "work": str(b.cells.get(C_WORK, ""))[:120],
            "place": str(b.cells.get(C_PLACE, "")), "appendices": len(b.appendices),
            "open_issues": open_by_act.get(number, 0)}


def _commit(ws: Workspace, state: State, blocks: list[Block], label: str) -> None:
    ws.snapshot(label)
    save(ws.registry_path, sort_blocks(blocks), ws.registry_path)
    ws.save_state(state)


# ---------- загрузка ----------

def _read_file(path: Path, read_scan: ReadScan | None) -> tuple[list[tuple[Act, list[dict]]], list[str]]:
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        if read_scan is None:
            raise AosrError("bad_file", f"{path.name}: разбор сканов не подключён")
        act, drafts, notes = read_scan(path)
        return [(act, drafts)], notes
    if suffix in (".xlsx", ".xlsm"):
        if is_registry(path):
            raise AosrError("bad_file", f"{path.name}: это реестр, а не книга с актами")
        acts, skipped = parse_workbook(path)
        return [(a, []) for a in acts], skipped
    raise AosrError("bad_file", f"{path.name}: неизвестный тип файла (нужен .xlsx или .pdf)")


def inspect(path: Path) -> dict:
    """Что за файл прислали: реестр, книга актов, скан или неизвестно что. Рабочая папка не нужна."""
    path = Path(path)
    if not path.is_file():
        raise AosrError("bad_file", f"{path.name}: файла нет")
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        return {"kind": "scan"}
    if suffix in (".xlsx", ".xlsm"):
        return {"kind": "registry" if is_registry(path) else "acts"}
    return {"kind": "unknown"}


def ingest(ws: Workspace, files: list[Path], *, read_scan: ReadScan | None = None) -> dict:
    ws.require()
    state = ws.load_state()
    blocks = load(ws.registry_path)
    by_key = {b.key: b for b in _acts(blocks)}
    added: list[str] = []
    updated: list[str] = []
    notes: list[dict] = []
    errors: list[dict] = []
    new_issues: list[dict] = []
    seen: dict[str, str] = {}
    state_changed = False

    for f in map(Path, files):
        try:
            parsed, file_notes = _read_file(f, read_scan)
        except AosrError as e:
            errors.append({"file": f.name, "code": e.code, "message": e.message})
            continue
        except Exception as e:  # один сломанный файл не должен ронять остальные
            errors.append({"file": f.name, "code": "internal_error", "message": f"{type(e).__name__}: {e}"})
            continue
        notes += [{"number": "", "text": f"{f.name}: {t}"} for t in file_notes]
        for act, drafts in parsed:
            number = clean_number(act.number)
            if not act.key:
                notes.append({"number": "", "text": f"{act.source}: нет номера акта — в реестр не внесён"})
                continue
            if act.key in state.deleted:
                notes.append({"number": number, "text": "удалён ранее — пропущен (вернуть: команда restore)"})
                continue
            if act.key in seen:
                notes.append({"number": number, "text": f"акт встречается в загрузке дважды ({seen[act.key]} и {act.source}) — взят последний"})
            seen[act.key] = act.source
            notes += [{"number": number, "text": w} for w in act.warnings]

            ov = state.overrides.get(act.key, {})
            cells, appendices = act_cells(act), list(act.appendices)
            _apply_overrides(cells, appendices, ov)
            key = norm_number(cells.get(C_NUM))
            shown = str(cells.get(C_NUM, number))
            old = by_key.get(key)

            issues, hold = _register_issues(state, act, drafts, ov, old, cells, appendices, shown)
            if issues:
                state_changed = True
                new_issues += issues
            if hold:
                continue
            if old is None:
                block = Block(cells=cells)
                block.appendices = appendices
                blocks.append(block)
                by_key[key] = block
                added.append(shown)
            else:
                _put(old, cells, appendices)
                if shown not in updated and shown not in added:
                    updated.append(shown)

    if added or updated:
        _commit(ws, state, blocks, f"загрузка: файлов {len(files)}, добавлено {len(added)}, обновлено {len(updated)}")
    elif state_changed:
        ws.snapshot("загрузка: новые вопросы")
        ws.save_state(state)
    return {"added": added, "updated": updated, "total": len(by_key), "issues": new_issues,
            "open_issues": len(state.open_issues()), "notes": notes, "errors": errors,
            "registry": str(ws.registry_path)}


def _diff_fields(block: Block, cells: dict[int, object], appendices: list[str]) -> list[str]:
    """Поля, по которым новый вариант акта отличается от записанного (после нормализации)."""
    out = [name for name, col in FIELD_COLS.items()
           if normalize(block.cells.get(col, "")) != normalize(cells.get(col, ""))]
    if [normalize(a) for a in block.appendices] != [normalize(a) for a in appendices]:
        out.append("appendices")
    return out


def _add_mismatches(state: State, shown: str, drafts: list[dict], ov: dict) -> list[dict]:
    """Вопросы о расхождении двух прочтений; на отвеченные и уже открытые не переспрашиваем."""
    out = []
    for d in drafts:
        if d.get("kind") != "mismatch" or d["field"] in ov:
            continue
        if d["field"] == "items" and all(k in ov for k in ("code", "work", "unit", "qty")):
            continue
        if any(i.field == d["field"] and norm_number(i.number) == norm_number(shown) for i in state.open_issues()):
            continue
        issue = state.new_issue(number=shown, kind="mismatch", field=d["field"],
                                options=list(d["options"]), fragments=list(d["fragments"]))
        out.append(asdict(issue))
    return out


def _register_issues(state, act, drafts, ov, old, cells, appendices, shown) -> tuple[list[dict], bool]:
    """Зарегистрировать спорные места акта. Возвращает новые вопросы и признак «акт не записывать»."""
    if act.origin == "scan" and old is not None:
        diff = _diff_fields(old, cells, appendices)
        if diff:
            payload = {"act": act.to_dict(), "drafts": drafts}
            for i in state.open_issues():
                if i.kind == "conflict" and norm_number(i.number) == norm_number(shown):
                    state.pending[i.id] = payload
                    i.fragments = [", ".join(diff)]
                    return [], True
            issue = state.new_issue(number=shown, kind="conflict", field="act",
                                    options=["заменить", "оставить"], fragments=[", ".join(diff)])
            state.pending[issue.id] = payload
            return [asdict(issue)], True
    return _add_mismatches(state, shown, drafts, ov), False


def issues(ws: Workspace, *, number: str | None = None) -> dict:
    ws.require()
    key = norm_number(number) if number else ""
    found = [asdict(i) for i in ws.load_state().open_issues() if not key or norm_number(i.number) == key]
    return {"issues": found, "open": len(found)}


# ---------- чтение ----------

def find(ws: Workspace, *, number: str | None = None, text: str | None = None,
         date_from: str | None = None, date_to: str | None = None) -> dict:
    ws.require()
    d1, d2 = _parse_iso(date_from, "date_from"), _parse_iso(date_to, "date_to")
    key = norm_number(number) if number else ""
    stems = _stems(text) if text else []
    open_by_act = _open_by_act(ws.load_state())
    acts = []
    for b in _acts(load(ws.registry_path)):
        if key and key not in b.key:
            continue
        if (d1 or d2) and (b.date is None or (d1 and b.date < d1) or (d2 and b.date > d2)):
            continue
        if stems:
            hay = _haystack(b)
            if not all(s in hay for s in stems):
                continue
        acts.append(_summary_of(b, open_by_act))
    return {"acts": acts, "count": len(acts)}


def show(ws: Workspace, number: str) -> dict:
    ws.require()
    b = _locate(load(ws.registry_path), number, partial=True)
    state = ws.load_state()
    num = str(b.cells[C_NUM])
    act = {"number": num, "date": _iso(b.date)}
    for name, col in FIELD_COLS.items():
        if name not in ("number", "date"):
            act[name] = str(b.cells.get(col, ""))
    act["appendices"] = b.appendices
    act["manual"] = {get_column_letter(c): v for c, v in sorted(b.cells.items()) if c not in AUTO_COLS}
    act["issues"] = [asdict(i) for i in state.open_issues() if norm_number(i.number) == b.key]
    return {"act": act}


def summary(ws: Workspace) -> dict:
    ws.require()
    acts = _acts(load(ws.registry_path))
    dates = sorted(b.date for b in acts if b.date)
    history = ws.history()
    return {"total": len(acts), "last_change": history[-1] if history else None, "date_from": _iso(dates[0]) if dates else None,
            "date_to": _iso(dates[-1]) if dates else None,
            "open_issues": len(ws.load_state().open_issues()), "history": len(history)}


def export(ws: Workspace) -> dict:
    ws.require()
    state = ws.load_state()
    return {"registry": str(ws.registry_path), "open_issues": len(state.open_issues()),
            "issues_by_act": _open_by_act(state)}


# ---------- изменение ----------

def _normalize_value(blocks: list[Block], block: Block, field: str, value: str) -> object:
    value = str(value).strip()
    if field == "date":
        m = _DATE.match(value.removesuffix("г.").strip())
        try:
            return fmt_date(date(int(m.group(3)), int(m.group(2)), int(m.group(1)))) if m else _bad_date(value)
        except ValueError:
            _bad_date(value)
    if field == "number":
        value = clean_number(value)
        if not value:
            raise AosrError("bad_value", "номер акта не может быть пустым")
        if any(b is not block and b.key == norm_number(value) for b in _acts(blocks)):
            raise AosrError("bad_value", f"акт с номером «{value}» уже есть в реестре")
    return value


def _bad_date(value: str):
    raise AosrError("bad_value", f"дата ожидается в виде ДД.ММ.ГГГГ, получено «{value}»")


def _set_in(blocks: list[Block], block: Block, state: State, field: str, value) -> tuple[object, object]:
    """Изменить поле акта и запомнить правку. Возвращает (было, стало). Реестр не сохраняет."""
    src = _src_key(state, block.key)
    shown = str(block.cells[C_NUM])
    ov = state.overrides.setdefault(src, {})
    m = _APPENDIX.match(field)
    if field == "appendices":
        old, new = block.appendices, [str(a) for a in value]
        block.appendices = new
        for name in [n for n in ov if _APPENDIX.match(n)]:
            del ov[name]
    elif field == "items":
        old = {k: str(block.cells.get(FIELD_COLS[k], "")) for k in ("code", "work", "unit", "qty")}
        new = {k: str(value.get(k, "")) for k in ("code", "work", "unit", "qty")}
        for k, v in new.items():
            _set_in(blocks, block, state, k, v)
        return old, new
    elif m:
        apps = block.appendices
        i = int(m.group(1)) - 1
        if not 0 <= i <= len(apps):
            raise AosrError("bad_value", f"у акта {len(apps)} приложений; допустимы appendix.1 … appendix.{len(apps) + 1}")
        new = str(value).strip()
        old = apps[i] if i < len(apps) else ""
        if new == "" and i < len(apps):
            del apps[i]
        elif i < len(apps):
            apps[i] = new
        elif new:
            apps.append(new)
        block.appendices = apps
    elif field in FIELD_COLS:
        col = FIELD_COLS[field]
        new = _normalize_value(blocks, block, field, value)
        old = str(block.cells.get(col, ""))
        if new == "":
            block.cells.pop(col, None)
        else:
            block.cells[col] = new
        if field == "number":
            for i in state.issues:
                if norm_number(i.number) == norm_number(shown):
                    i.number = str(new)
    else:
        raise AosrError("bad_field", f"неизвестное поле «{field}»; допустимы: {', '.join(FIELD_COLS)}, appendix.N")
    ov[field] = new
    return old, new


def set_field(ws: Workspace, number: str, field: str, value: str) -> dict:
    ws.require()
    if field in ("appendices", "items"):
        raise AosrError("bad_field", f"поле «{field}» целиком не правится; используйте appendix.N или code/work/unit/qty")
    blocks = load(ws.registry_path)
    block = _locate(blocks, number)
    state = ws.load_state()
    shown = str(block.cells[C_NUM])
    old, new = _set_in(blocks, block, state, field, value)
    _commit(ws, state, blocks, f"исправлено поле {field} акта {shown}")
    return {"number": str(block.cells[C_NUM]), "field": field, "old": old, "new": new}


def resolve(ws: Workspace, issue_id: str, answer: str, *, literal: bool = False) -> dict:
    """Ответить на вопрос. literal — ответ есть само значение поля, даже если это «1» или «2»."""
    ws.require()
    state = ws.load_state()
    issue = next((i for i in state.open_issues() if i.id == issue_id), None)
    if issue is None:
        raise AosrError("issue_not_found", f"открытого вопроса «{issue_id}» нет")
    answer = str(answer).strip()
    blocks = load(ws.registry_path)
    pick = int(answer) - 1 if answer in ("1", "2") and not literal else None
    if issue.kind == "conflict":
        if pick is None:
            raise AosrError("bad_value", "ответ на этот вопрос: 1 — заменить, 2 — оставить")
        payload = state.pending.pop(issue.id, None)
        value = issue.options[pick]
        if pick == 0 and payload:
            act = Act.from_dict(payload["act"])
            ov = state.overrides.get(act.key, {})
            cells, appendices = act_cells(act), list(act.appendices)
            _apply_overrides(cells, appendices, ov)
            key = norm_number(cells.get(C_NUM))
            block = next((b for b in _acts(blocks) if b.key == key), None)
            if block is None:
                block = Block(cells={})
                blocks.append(block)
            _put(block, cells, appendices)
            _add_mismatches(state, str(cells.get(C_NUM)), payload.get("drafts", []), ov)
    else:
        block = _locate(blocks, issue.number)
        if pick is not None:
            value = issue.options[pick]
        elif issue.field in ("items", "appendices"):
            raise AosrError("bad_value", "на этот вопрос можно ответить только 1 или 2")
        else:
            value = answer
        _, value = _set_in(blocks, block, state, issue.field, value)
    issue.status, issue.chosen = "resolved", str(value)
    _commit(ws, state, blocks, f"ответ на вопрос {issue.id} по акту {issue.number}")
    return {"issue": issue.id, "number": issue.number, "field": issue.field, "value": value}


def _forget(state: State, block: Block, *, tombstone: bool) -> str:
    """Убрать из состояния всё про акт. Возвращает его номер."""
    shown = str(block.cells[C_NUM])
    src = _src_key(state, block.key)
    state.overrides.pop(src, None)
    if tombstone:
        state.deleted[src] = shown
    gone = [i.id for i in state.issues if norm_number(i.number) == block.key]
    state.issues = [i for i in state.issues if i.id not in gone]
    for q in gone:
        state.pending.pop(q, None)
    return shown


def replace_registry(ws: Workspace, file: str | Path, *, missing: str = "check") -> dict:
    """Принять реестр, который человек правил у себя, как текущий."""
    ws.require()
    if missing not in ("check", "keep", "drop"):
        raise AosrError("bad_value", "missing: check, keep или drop")
    file = Path(file)
    if not is_registry(file):
        raise AosrError("bad_file", f"{file.name}: это не реестр (нет листа «общий» с шапкой таблицы)")
    incoming = load(file)
    current = {b.key: b for b in _acts(load(ws.registry_path))}
    theirs = {b.key: b for b in _acts(incoming)}
    lost = [b for k, b in current.items() if k not in theirs]
    if missing == "check":
        return {"missing": [str(b.cells[C_NUM]) for b in lost], "incoming_total": len(theirs)}

    stray = drop_stray(incoming)
    state = ws.load_state()
    edits = 0
    for key, b in theirs.items():
        old = current.get(key)
        if old is None:
            continue
        ov = state.overrides.setdefault(_src_key(state, key), {})
        for name, col in FIELD_COLS.items():
            if name != "number" and str(b.cells.get(col, "")) != str(old.cells.get(col, "")):
                ov[name] = str(b.cells.get(col, ""))
                edits += 1
        if b.appendices != old.appendices:
            for name in [n for n in ov if _APPENDIX.match(n)]:
                del ov[name]
            ov["appendices"] = b.appendices
            edits += 1
    state.overrides = {k: v for k, v in state.overrides.items() if v}

    kept, dropped = [], []
    if missing == "keep":
        incoming += lost
        kept = [str(b.cells[C_NUM]) for b in lost]
    else:
        dropped = [_forget(state, b, tombstone=True) for b in lost]
    ws.snapshot(f"принят реестр из файла {file.name}")
    if file.resolve() != ws.registry_path.resolve():
        shutil.copy2(file, ws.registry_path)
    save(ws.registry_path, sort_blocks(incoming), ws.registry_path)
    ws.save_state(state)
    return {"total": len(_acts(incoming)), "kept": kept, "dropped": dropped, "manual_edits": edits,
            "stray_rows": stray}


def delete(ws: Workspace, number: str) -> dict:
    ws.require()
    blocks = load(ws.registry_path)
    block = _locate(blocks, number)
    state = ws.load_state()
    blocks.remove(block)
    shown = _forget(state, block, tombstone=True)
    _commit(ws, state, blocks, f"удалён акт {shown}")
    return {"number": shown, "removed_rows": block.rows}


def restore(ws: Workspace, number: str) -> dict:
    """Снять отметку «удалён»: при следующей загрузке акт снова попадёт в реестр."""
    ws.require()
    state = ws.load_state()
    key = norm_number(number)
    for src, shown in list(state.deleted.items()):
        if key in (src, norm_number(shown)):
            del state.deleted[src]
            ws.save_state(state)
            return {"number": shown}
    raise AosrError("act_not_found", f"среди удалённых нет акта «{number}»")


def undo(ws: Workspace) -> dict:
    ws.require()
    return {"undone": ws.undo()}
