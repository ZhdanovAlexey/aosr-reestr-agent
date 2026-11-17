"""Нормализация текста и сравнение двух прочтений одного акта."""
from __future__ import annotations

import re

_QUOTES = str.maketrans({"«": '"', "»": '"', "“": '"', "”": '"', "„": '"', "‟": '"', "'": '"', "’": '"', "‘": '"',
                         "–": "-", "—": "-", "−": "-", "‑": "-", "ё": "е"})


def normalize(text) -> str:
    """Свести к виду, в котором косметические различия не считаются расхождением."""
    s = str(text if text is not None else "").lower().translate(_QUOTES)
    s = re.sub(r"\s+", " ", s)
    s = re.sub(r"\s*([/\-,;:()])\s*", r"\1", s)
    s = re.sub(r"№\s+", "№", s)
    return s.strip().rstrip(";.").strip()


def diff_fragments(a: str, b: str, context: int = 3) -> list[str]:
    """По короткому фрагменту на вариант: расходящиеся слова и несколько соседних."""
    from difflib import SequenceMatcher

    ta, tb = str(a).split(), str(b).split()
    ops = [o for o in SequenceMatcher(None, ta, tb, autojunk=False).get_opcodes() if o[0] != "equal"]
    if not ops:
        return [str(a), str(b)]

    def cut(tokens: list[str], lo: int, hi: int) -> str:
        lo, hi = max(0, lo - context), min(len(tokens), hi + context)
        return " ".join((["…"] if lo > 0 else []) + tokens[lo:hi] + (["…"] if hi < len(tokens) else []))

    return [cut(ta, ops[0][1], ops[-1][2]), cut(tb, ops[0][3], ops[-1][4])]


def _plural_rows(n: int) -> str:
    word = "строка" if n % 10 == 1 and n % 100 != 11 else "строки" if n % 10 in (2, 3, 4) and n % 100 not in (12, 13, 14) else "строк"
    return f"{n} {word} работ"


def _question(field: str, options: list, fragments: list[str]) -> dict:
    return {"kind": "mismatch", "field": field, "options": options, "fragments": fragments}


def compare_acts(primary, secondary) -> list[dict]:
    """Заготовки вопросов по полям, которые две модели прочли по-разному."""
    from .registry import FIELD_COLS, act_cells

    ca, cb = act_cells(primary), act_cells(secondary)
    val = lambda cells, name: str(cells.get(FIELD_COLS[name], ""))
    out: list[dict] = []
    for name in ("number", "date", "place"):
        a, b = val(ca, name), val(cb, name)
        if normalize(a) != normalize(b):
            out.append(_question(name, [a, b], [a, b]))

    line_fields = ("code", "work", "unit", "qty")
    if len(primary.items) != len(secondary.items):
        out.append(_question("items", [{n: val(c, n) for n in line_fields} for c in (ca, cb)],
                             [_plural_rows(len(primary.items)), _plural_rows(len(secondary.items))]))
    else:
        for name in line_fields:
            a, b = val(ca, name), val(cb, name)
            if normalize(a) == normalize(b):
                continue
            la, lb = a.split("\n"), b.split("\n")
            pairs = [(x, y) for x, y in zip(la, lb) if normalize(x) != normalize(y)] if len(la) == len(lb) else []
            if not pairs:
                fragments = [a, b]
            elif name == "work":
                fragments = diff_fragments(*pairs[0])
            else:
                fragments = ["; ".join(x for x, _ in pairs), "; ".join(y for _, y in pairs)]
            out.append(_question(name, [a, b], fragments))

    aa, ab = list(primary.appendices), list(secondary.appendices)
    if len(aa) != len(ab):
        out.append(_question("appendices", [aa, ab], [f"приложений: {len(aa)}", f"приложений: {len(ab)}"]))
    else:
        for n, (x, y) in enumerate(zip(aa, ab), 1):
            if normalize(x) != normalize(y):
                out.append(_question(f"appendix.{n}", [x, y], diff_fragments(x, y)))
    return out
