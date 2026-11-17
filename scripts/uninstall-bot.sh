#!/bin/bash
# Остановить и убрать службу бота. Реестр, история и настройки остаются на месте.
set -euo pipefail
LABEL=com.azhdanov.aosr-bot
launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null && echo "Служба остановлена." || echo "Служба не была запущена."
rm -f "$HOME/Library/LaunchAgents/$LABEL.plist"
