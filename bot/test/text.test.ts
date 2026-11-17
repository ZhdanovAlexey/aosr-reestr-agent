import { expect, test } from "vitest";
import { actIssues, chunks, confirmQuestion, fieldName, ingestReport, type Issue, plain, registryCaption, replaceQuestion } from "../src/text.js";

const base = { added: [], updated: [], total: 0, issues: [], open_issues: 0, notes: [], errors: [] };
const bytes = (s: string) => Buffer.byteLength(s, "utf8");

test("ingest report: counts, notes, errors, open questions", () => {
  const r = { ...base, added: ["А/1", "А/2"], updated: ["А/3"], total: 10, open_issues: 2,
    notes: [{ number: "А/1", text: "из скана — сверь с оригиналом" }, { number: "", text: "книга.xlsx: лист «Лист1» пропущен" }],
    errors: [{ file: "x.pdf", code: "model_error", message: "обе модели не справились" }] };
  expect(ingestReport("книга.xlsx", r)).toBe([
    "«книга.xlsx»: добавлено 2, обновлено 1. Всего актов в реестре: 10.",
    "Замечания:",
    "№ А/1: из скана — сверь с оригиналом",
    "книга.xlsx: лист «Лист1» пропущен",
    "Не разобрано:",
    "x.pdf: обе модели не справились",
    "Открытых вопросов: 2.",
  ].join("\n"));
});

test("ingest report without notes is one line", () => {
  expect(ingestReport("a.xlsx", { ...base, added: ["А/1"], total: 1 })).toBe("«a.xlsx»: добавлено 1, обновлено 0. Всего актов в реестре: 1.");
});

test("ingest report caps notes at 15", () => {
  const notes = Array.from({ length: 22 }, (_, i) => ({ number: `А/${i}`, text: "нет «на участке»" }));
  const lines = ingestReport("a.xlsx", { ...base, notes }).split("\n");
  expect(lines.filter((l) => l.startsWith("№ ")).length).toBe(15);
  expect(lines.at(-1)).toBe("… и ещё 7");
});

const q = (o: Partial<Issue>): Issue => ({ id: "q1", number: "ЗР/ВГ/1", kind: "mismatch", field: "qty", options: ["812,45", "812,48"], fragments: [], ...o });

test("mismatch question shows both readings and three buttons", () => {
  const m = actIssues("ЗР/ВГ/1", [q({})]);
  expect(m.text).toBe("Акт № ЗР/ВГ/1 — вопросы (1):\n1. количество: прочитано по-разному.\n   1) 812,45\n   2) 812,48");
  expect(m.buttons).toEqual([[
    { label: "1: вариант 1", data: "q:q1:1" }, { label: "1: вариант 2", data: "q:q1:2" }, { label: "1: напишу сам", data: "q:q1:own" },
  ]]);
});

test("long fields show fragments, list fields have no free answer", () => {
  const m = actIssues("А/1", [
    q({ id: "q2", field: "appendix.3", options: ["Акт отбора проб №СТЛ/1/ФМС - 1 лист", "Акт отбора проб №ССТЛ 1/ФМС - 1 лист"], fragments: ["СТЛ/1/ФМС", "ССТЛ 1/ФМС"] }),
    q({ id: "q3", field: "appendices", options: [["а", "б"], ["а"]], fragments: [] }),
  ]);
  expect(m.text).toBe("Акт № А/1 — вопросы (2):\n1. приложение 3: прочитано по-разному.\n   1) СТЛ/1/ФМС\n   2) ССТЛ 1/ФМС\n2. приложения: прочитано по-разному.\n   1) а; б\n   2) а");
  expect(m.buttons![0].map((b) => b.data)).toEqual(["q:q2:1", "q:q2:2", "q:q2:own"]);
  expect(m.buttons![1].map((b) => b.data)).toEqual(["q:q3:1", "q:q3:2"]);
});

test("conflict question offers replace or keep", () => {
  const m = actIssues("А/1", [q({ id: "q7", kind: "conflict", field: "act", options: ["заменить", "оставить"], fragments: ["qty, appendices"] })]);
  expect(m.text).toBe("Акт № А/1 — вопросы (1):\n1. Акт уже есть в реестре и отличается от скана (количество, приложения). Заменить данными из скана?");
  expect(m.buttons).toEqual([[{ label: "1: заменить", data: "q:q7:1" }, { label: "1: оставить", data: "q:q7:2" }]]);
});

test("no questions left", () => {
  expect(actIssues("А/1", [])).toEqual({ text: "Акт № А/1: вопросов не осталось." });
});

test("field names", () => {
  expect(["code", "work", "date", "number", "unit", "place", "items", "appendix.12", "что-то"].map(fieldName)).toEqual(
    ["№ по ведомости", "наименование работ", "дата", "номер акта", "единица", "место", "строки работ", "приложение 12", "что-то"]);
});

test("registry caption", () => {
  expect(registryCaption({ open_issues: 0, issues_by_act: {} }, 64)).toBe("Реестр: актов 64.");
  expect(registryCaption({ open_issues: 3, issues_by_act: { "А/1": 2, "Б/2": 1 } }, 64)).toBe("Реестр: актов 64.\nОткрытых вопросов: 3 (акты: А/1, Б/2).");
  const many = Object.fromEntries(Array.from({ length: 14 }, (_, i) => [`А/${i}`, 1]));
  expect(registryCaption({ open_issues: 14, issues_by_act: many }, 64)).toContain("А/9 и ещё 4)");
});

test("confirmation questions", () => {
  expect(confirmQuestion({ kind: "delete", number: "ВО/4-9/ОЗ" }, "ab12cd34")).toEqual({
    text: "Удалить акт № ВО/4-9/ОЗ вместе с приложениями?",
    buttons: [[{ label: "Удалить", data: "c:ab12cd34:yes" }, { label: "Отмена", data: "c:ab12cd34:no" }]] });
  expect(confirmQuestion({ kind: "undo", label: "удалён акт А/1" }, "ab12cd34")).toEqual({
    text: "Отменить последнее изменение: «удалён акт А/1»?",
    buttons: [[{ label: "Отменить изменение", data: "c:ab12cd34:yes" }, { label: "Не надо", data: "c:ab12cd34:no" }]] });
});

test("replace question without and with missing acts", () => {
  expect(replaceQuestion("р.xlsx", { missing: [], incoming_total: 64 }, 64, "id000001")).toEqual({
    text: "«р.xlsx» — это реестр: актов 64 (сейчас в реестре 64). Сделать его текущим?",
    buttons: [[{ label: "Заменить", data: "c:id000001:keep" }, { label: "Отмена", data: "c:id000001:no" }]] });
  const m = replaceQuestion("р.xlsx", { missing: Array.from({ length: 12 }, (_, i) => `А/${i}`), incoming_total: 52 }, 64, "id000001");
  expect(m.text).toBe("«р.xlsx» — это реестр: актов 52 (сейчас в реестре 64). Сделать его текущим?\nВ нём нет актов, которые есть сейчас (12): А/0, А/1, А/2, А/3, А/4, А/5, А/6, А/7, А/8, А/9…");
  expect(m.buttons!.map((row) => row[0])).toEqual([
    { label: "Заменить, эти акты оставить", data: "c:id000001:keep" },
    { label: "Заменить, эти акты удалить", data: "c:id000001:drop" },
    { label: "Отмена", data: "c:id000001:no" }]);
});

test("plain strips markdown but keeps slashes and numbers", () => {
  expect(plain("**Акт** `ЗР/ВГ/1`\n# Итог\n|---|---|\n| a | b |")).toBe("Акт ЗР/ВГ/1\nИтог\n| a | b |");
  expect(plain("__важно__ и file_name_x, 2*3*4")).toBe("важно и file_name_x, 2*3*4");
});

test("chunks never exceed the limit and lose nothing", () => {
  const src = "строка\n".repeat(3000);
  const parts = chunks(src);
  expect(parts.length).toBeGreaterThan(1);
  expect(parts.every((p) => p.length <= 4000 && p.length > 0)).toBe(true);
  expect(parts.join("\n")).toBe(src.trim());
});

test("chunks split a single over-long line and skip empty text", () => {
  expect(chunks("я".repeat(9000)).map((p) => p.length)).toEqual([4000, 4000, 1000]);
  expect(chunks("  \n ")).toEqual([]);
  expect(chunks("привет")).toEqual(["привет"]);
});

test("button data fits 64 bytes", () => {
  const all = [
    ...actIssues("А/1", [q({ id: "q1234567" })]).buttons!.flat(),
    ...confirmQuestion({ kind: "delete", number: "А/1" }, "ab12cd34").buttons!.flat(),
    ...replaceQuestion("р.xlsx", { missing: ["А/1"], incoming_total: 1 }, 2, "ab12cd34").buttons!.flat(),
  ];
  for (const b of all) expect(bytes(b.data)).toBeLessThanOrEqual(64);
});

import { factCheck } from "../src/text.js";

test("fact check: a claim of change without a change gets a correction", () => {
  const idle = { registryChanged: false, confirmations: 0 };
  expect(factCheck("Я удалил акты за август.", idle)).toBe("Уточнение от бота: в этом ходе реестр не менялся.");
  expect(factCheck("Акт удалён, место исправлено.", idle)).toBe("Уточнение от бота: в этом ходе реестр не менялся.");
  expect(factCheck("Изменение отменено.", idle)).toBe("Уточнение от бота: в этом ходе реестр не менялся.");
  expect(factCheck("Я запросил удаление, акт удалён.", { registryChanged: false, confirmations: 1 }))
    .toBe("Уточнение от бота: в этом ходе реестр не менялся. Действие выполнится только после нажатия кнопки.");
});

test("fact check stays silent when nothing is claimed or the registry did change", () => {
  const idle = { registryChanged: false, confirmations: 0 };
  expect(factCheck("Жду нажатия кнопки, чтобы удалить акт.", idle)).toBeUndefined();
  expect(factCheck("Я не могу удалять акты без подтверждения.", idle)).toBeUndefined();
  expect(factCheck("В августе 4 акта.", idle)).toBeUndefined();
  expect(factCheck("Исправил место.", { registryChanged: true, confirmations: 0 })).toBeUndefined();
});
