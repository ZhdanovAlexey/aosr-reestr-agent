#!/bin/bash
# Сквозная проверка на примерах из examples/ и живых моделях (нужен ключ хаба): каждая команда печатает свой JSON.
#   bash scripts/smoke.sh [папка для результата]
set -euo pipefail
cd "$(dirname "$0")/.."
HOME_DIR="${1:-$(mktemp -d)/aosr-home}"
PY=.venv/bin/python
TEMPLATE="examples/registry_template.xlsx"
BOOK="examples/acts.xlsx"
SCAN="examples/act_scan.pdf"

run() {
  echo "── aosr $*" >&2
  local out
  out=$($PY -m aosr --home "$HOME_DIR" "$@") || { echo "$out"; echo "КОМАНДА УПАЛА: $*" >&2; exit 1; }
  echo "$out" | $PY -c 'import json,sys; d=json.load(sys.stdin); s=json.dumps(d, ensure_ascii=False); print(s[:700] + (" …" if len(s) > 700 else ""))'
  LAST="$out"
}

run init --template "$TEMPLATE"
run ingest "$BOOK"
run ingest "$SCAN"
run issues
FIRST=$(echo "$LAST" | $PY -c 'import json,sys; q=json.load(sys.stdin)["issues"]; print(q[0]["id"] if q else "")')
if [ -n "$FIRST" ]; then run resolve "$FIRST" 2; fi
run set "ВО/11-15/БО" place "колодцы 11-15"
run delete "ВО/4-9/ОЗ"
run undo
run find --text "обратная засыпка"
run show "ЗР/ВГ/1"
run summary
run export
echo "Рабочая папка: $HOME_DIR" >&2
