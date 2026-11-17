#!/bin/bash
# Поставить бота службой launchd: проверяет настройки и токен, создаёт реестр, запускает.
#   bash scripts/install-bot.sh
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
LABEL=com.azhdanov.aosr-bot
CONFIG="${AOSR_BOT_CONFIG:-$HOME/.config/aosr-bot/config.json}"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
LOG="$HOME/Library/Logs/aosr-bot/bot.log"
# свой шаблон реестра: AOSR_TEMPLATE=/путь/к/шаблону.xlsx bash scripts/install-bot.sh
TEMPLATE="${AOSR_TEMPLATE:-$ROOT/examples/registry_template.xlsx}"
NODE="$(command -v node || true)"

fail() { echo "Не хватает: $1" >&2; exit 1; }

[ -n "$NODE" ] || fail "node в PATH"
[ -d "$ROOT/bot/node_modules" ] || fail "зависимостей бота — выполните: (cd bot && npm install)"
[ -x "$ROOT/.venv/bin/python" ] || fail "окружения ядра — выполните: python3 -m venv .venv && .venv/bin/pip install -e ."
if [ ! -f "$CONFIG" ]; then
  cat >&2 <<MSG
Не хватает: файла настроек $CONFIG. Пример:
{
  "allowed": [ВАШ_TELEGRAM_ID],
  "home": "~/.local/share/aosr-bot/home",
  "python": "$ROOT/.venv/bin/python",
  "tokenCmd": "security find-generic-password -s aosr-bot -w"
}
Токен кладётся в связку ключей командой (значение спросит терминал):
  security add-generic-password -U -s aosr-bot -a token -w
MSG
  exit 1
fi

INFO="$(cd "$ROOT/bot" && AOSR_BOT_CONFIG="$CONFIG" "$NODE" node_modules/tsx/dist/cli.mjs src/preflight.ts)" || fail "см. сообщение выше (настройки или токен)"
BOT_HOME="$("$NODE" -e 'console.log(JSON.parse(process.argv[1]).home)' "$INFO")"
PY="$("$NODE" -e 'console.log(JSON.parse(process.argv[1]).python)' "$INFO")"

if [ ! -f "$BOT_HOME/registry.xlsx" ]; then
  [ -f "$TEMPLATE" ] || fail "шаблона реестра $TEMPLATE"
  mkdir -p "$BOT_HOME"
  "$PY" -m aosr --home "$BOT_HOME" init --template "$TEMPLATE"
  echo "Создан чистый реестр: $BOT_HOME/registry.xlsx"
fi

mkdir -p "$(dirname "$LOG")" "$(dirname "$PLIST")"
chmod 600 "$CONFIG"
sed -e "s|@NODE@|$NODE|g" -e "s|@NODE_DIR@|$(dirname "$NODE")|g" -e "s|@ROOT@|$ROOT|g" -e "s|@HOME@|$HOME|g" \
    -e "s|@CONFIG@|$CONFIG|g" -e "s|@LOG@|$LOG|g" "$ROOT/deploy/$LABEL.plist.template" > "$PLIST"
plutil -lint "$PLIST" >/dev/null

DOMAIN="gui/$(id -u)"
launchctl bootout "$DOMAIN/$LABEL" 2>/dev/null || true
# прежний экземпляр останавливается не мгновенно: ждём, пока служба исчезнет, и повторяем запуск
for _ in 1 2 3 4 5 6 7 8 9 10; do
  launchctl print "$DOMAIN/$LABEL" >/dev/null 2>&1 || break
  sleep 1
done
started=""
for _ in 1 2 3 4 5; do
  if launchctl bootstrap "$DOMAIN" "$PLIST" 2>/dev/null; then started=1; break; fi
  sleep 2
done
[ -n "$started" ] || { echo "Служба не запустилась: launchctl bootstrap $DOMAIN $PLIST" >&2; exit 1; }
echo "Служба $LABEL запущена. Журнал: $LOG"
