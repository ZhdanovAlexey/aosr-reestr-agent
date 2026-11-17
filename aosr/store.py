"""Рабочая папка: текущий реестр, история версий, состояние (вопросы, ручные правки)."""
from __future__ import annotations

import json
import shutil
from dataclasses import asdict, dataclass, field
from pathlib import Path

from .errors import AosrError
from .registry import init_registry

HISTORY_LIMIT = 50


@dataclass
class Issue:
    id: str
    number: str
    kind: str  # "mismatch" — две модели прочли по-разному; "conflict" — акт уже есть и отличается
    field: str
    options: list
    fragments: list[str]
    status: str = "open"
    chosen: str | None = None


@dataclass
class State:
    issues: list[Issue] = field(default_factory=list)
    overrides: dict[str, dict[str, object]] = field(default_factory=dict)  # ключ акта -> поле -> значение
    pending: dict[str, dict] = field(default_factory=dict)  # id вопроса -> Act.to_dict()
    deleted: dict[str, str] = field(default_factory=dict)  # ключ акта в источнике -> номер; повторная загрузка такие пропускает
    next_issue: int = 1

    def new_issue(self, **kw) -> Issue:
        issue = Issue(id=f"q{self.next_issue}", **kw)
        self.next_issue += 1
        self.issues.append(issue)
        return issue

    def open_issues(self) -> list[Issue]:
        return [i for i in self.issues if i.status == "open"]


class Workspace:
    def __init__(self, home: str | Path):
        self.home = Path(home)
        self.registry_path = self.home / "registry.xlsx"
        self.inbox = self.home / "inbox"
        self._state = self.home / "state.json"
        self._history = self.home / "history"

    def init(self, template: str | Path) -> None:
        if self.registry_path.exists():
            raise AosrError("already_initialized", f"реестр уже создан: {self.registry_path}")
        self.inbox.mkdir(parents=True, exist_ok=True)
        self._history.mkdir(exist_ok=True)
        init_registry(template, self.registry_path)
        self.save_state(State())

    def require(self) -> None:
        if not self.registry_path.exists():
            raise AosrError("no_registry", f"в папке {self.home} нет реестра — сначала команда init")

    def load_state(self) -> State:
        if not self._state.exists():
            return State()
        d = json.loads(self._state.read_text(encoding="utf-8"))
        d["issues"] = [Issue(**i) for i in d.get("issues", [])]
        return State(**d)

    def save_state(self, state: State) -> None:
        tmp = self._state.with_suffix(".tmp")
        tmp.write_text(json.dumps(asdict(state), ensure_ascii=False, indent=1), encoding="utf-8")
        tmp.replace(self._state)

    def _versions(self) -> list[Path]:
        return sorted(p for p in self._history.iterdir() if p.is_dir()) if self._history.exists() else []

    def history(self) -> list[str]:
        return [(p / "label.txt").read_text(encoding="utf-8") for p in self._versions()]

    def snapshot(self, label: str) -> None:
        """Сохранить текущие реестр и состояние перед изменением."""
        versions = self._versions()
        n = int(versions[-1].name) + 1 if versions else 1
        d = self._history / f"{n:06d}"
        d.mkdir(parents=True)
        shutil.copy2(self.registry_path, d / "registry.xlsx")
        if self._state.exists():
            shutil.copy2(self._state, d / "state.json")
        (d / "label.txt").write_text(label, encoding="utf-8")
        for old in self._versions()[:-HISTORY_LIMIT]:
            shutil.rmtree(old)

    def undo(self) -> str:
        """Вернуть реестр и состояние к последнему сохранённому. Возвращает подпись отменённого изменения."""
        versions = self._versions()
        if not versions:
            raise AosrError("nothing_to_undo", "отменять нечего: история изменений пуста")
        last = versions[-1]
        counter = self.load_state().next_issue  # номера вопросов не переиспользуются: на старых кнопках остались прежние
        label = (last / "label.txt").read_text(encoding="utf-8")
        shutil.copy2(last / "registry.xlsx", self.registry_path)
        if (last / "state.json").exists():
            shutil.copy2(last / "state.json", self._state)
        else:
            self._state.unlink(missing_ok=True)
        state = self.load_state()
        if state.next_issue < counter:
            state.next_issue = counter
            self.save_state(state)
        shutil.rmtree(last)
        return label
