"""Записать ответы живых моделей на скан — эталон для тестов, которые не ходят в сеть.

    .venv/bin/python scripts/record_scan_fixture.py "путь/к/скану.pdf" tests/fixtures/scan_example
"""
import json
import sys
from pathlib import Path

from aosr.scan import PRIMARY_MODEL, SECONDARY_MODEL, render_pages, transcribe

pdf, out = Path(sys.argv[1]), Path(sys.argv[2])
out.mkdir(parents=True, exist_ok=True)
images = render_pages(pdf)
for model in (PRIMARY_MODEL, SECONDARY_MODEL):
    raw = transcribe(images, model)
    (out / f"{model}.json").write_text(json.dumps(raw, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(model, "ok:", raw["номер_акта"], raw["дата_акта"], len(raw["работы"]), "работ,", len(raw["приложения"]), "приложений")
