"""python -m aosr --home ПАПКА <команда> … — каждая команда печатает один JSON-объект."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import ops
from .errors import AosrError
from .store import Workspace


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="aosr", description=__doc__)
    ap.add_argument("--home", required=True, help="рабочая папка с реестром")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("init", help="создать чистый реестр из шаблона")
    p.add_argument("--template", required=True)
    p = sub.add_parser("ingest", help="разобрать акты и внести в реестр")
    p.add_argument("files", nargs="+")
    p = sub.add_parser("find", help="найти акты")
    p.add_argument("--number")
    p.add_argument("--text")
    p.add_argument("--from", dest="date_from")
    p.add_argument("--to", dest="date_to")
    for name, help_ in (("show", "показать акт"), ("delete", "удалить акт"), ("restore", "снять отметку «удалён»")):
        sub.add_parser(name, help=help_).add_argument("number")
    p = sub.add_parser("set", help="исправить поле акта")
    p.add_argument("number")
    p.add_argument("field")
    p.add_argument("value")
    sub.add_parser("inspect", help="что это за файл: реестр, книга актов или скан").add_argument("file")
    p = sub.add_parser("issues", help="открытые вопросы")
    p.add_argument("--number")
    p = sub.add_parser("resolve", help="ответить на вопрос")
    p.add_argument("issue")
    p.add_argument("answer")
    p.add_argument("--literal", action="store_true", help="ответ — само значение поля, а не номер варианта")
    p = sub.add_parser("replace-registry", help="принять реестр, правленный вручную")
    p.add_argument("file")
    p.add_argument("--missing", default="check", choices=["check", "keep", "drop"])
    for name, help_ in (("summary", "сводка по реестру"), ("export", "путь к реестру"), ("undo", "отменить последнее изменение")):
        sub.add_parser(name, help=help_)
    return ap


def dispatch(ws: Workspace, a: argparse.Namespace) -> dict:
    match a.cmd:
        case "init":
            ws.init(a.template)
            return {}
        case "inspect":
            return ops.inspect(Path(a.file))
        case "ingest":
            from .scan import read_scan
            return ops.ingest(ws, [Path(f) for f in a.files], read_scan=read_scan)
        case "find":
            return ops.find(ws, number=a.number, text=a.text, date_from=a.date_from, date_to=a.date_to)
        case "show":
            return ops.show(ws, a.number)
        case "set":
            return ops.set_field(ws, a.number, a.field, a.value)
        case "delete":
            return ops.delete(ws, a.number)
        case "restore":
            return ops.restore(ws, a.number)
        case "issues":
            return ops.issues(ws, number=a.number)
        case "resolve":
            return ops.resolve(ws, a.issue, a.answer, literal=a.literal)
        case "replace-registry":
            return ops.replace_registry(ws, a.file, missing=a.missing)
        case "summary":
            return ops.summary(ws)
        case "export":
            return ops.export(ws)
        case "undo":
            return ops.undo(ws)
    raise AosrError("bad_command", f"неизвестная команда {a.cmd}")


def main(argv: list[str] | None = None) -> int:
    a = build_parser().parse_args(argv)
    try:
        out = {"ok": True, **dispatch(Workspace(a.home), a)}
        code = 0
    except AosrError as e:
        out = {"ok": False, "error": {"code": e.code, "message": e.message}}
        code = 1
    except Exception as e:  # ответ всегда JSON: вызывающий код не разбирает трассировки
        out = {"ok": False, "error": {"code": "internal_error", "message": f"{type(e).__name__}: {e}"}}
        code = 1
    json.dump(out, sys.stdout, ensure_ascii=False)
    sys.stdout.write("\n")
    return code


if __name__ == "__main__":
    sys.exit(main())
