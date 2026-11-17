// Тексты, которые бот пишет сам (без модели): отчёты, вопросы с кнопками, подтверждения.
import type { Action } from "./confirm.js";

export interface Issue { id: string; number: string; kind: "mismatch" | "conflict"; field: string; options: unknown[]; fragments: string[] }
export interface IngestResult {
  added: string[]; updated: string[]; total: number; issues: Issue[]; open_issues: number;
  notes: { number: string; text: string }[]; errors: { file: string; code: string; message: string }[];
}
export interface Button { label: string; data: string }
export interface Outgoing { text: string; buttons?: Button[][] }

export const FIELD_NAMES: Record<string, string> = {
  code: "№ по ведомости", work: "наименование работ", date: "дата", number: "номер акта", unit: "единица",
  qty: "количество", place: "место", items: "строки работ", appendices: "приложения", act: "акт",
};
const NOTES_LIMIT = 15;
const LIST_LIMIT = 10;

export function fieldName(field: string): string {
  const m = /^appendix\.(\d+)$/.exec(field);
  return m ? `приложение ${m[1]}` : FIELD_NAMES[field] ?? field;
}

/** Убрать разметку Markdown, которую любит модель: Telegram получает простой текст. */
export function plain(text: string): string {
  return text
    .split("\n")
    .filter((l) => !/^\s*\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)*\|?\s*$/.test(l))
    .map((l) => l.replace(/^\s{0,3}#{1,6}\s+/, ""))
    .join("\n")
    .replace(/\*\*/g, "")
    .replace(/`/g, "")
    .replace(/(^|[^\p{L}\p{N}_])__(?=\S)(.+?)(?<=\S)__(?![\p{L}\p{N}_])/gu, "$1$2");
}

/** Разбить на сообщения не длиннее limit: по переводам строк, слишком длинную строку — по limit. */
export function chunks(text: string, limit = 4000): string[] {
  const out: string[] = [];
  let cur = "";
  const flush = () => { if (cur.trim()) out.push(cur); cur = ""; };
  for (let line of text.trim().split("\n")) {
    while (line.length > limit) {
      flush();
      out.push(line.slice(0, limit));
      line = line.slice(limit);
    }
    if (cur && cur.length + 1 + line.length > limit) flush();
    cur = cur ? `${cur}\n${line}` : line;
  }
  flush();
  return out;
}

export function ingestReport(fileName: string, r: IngestResult): string {
  const lines = [`«${fileName}»: добавлено ${r.added.length}, обновлено ${r.updated.length}. Всего актов в реестре: ${r.total}.`];
  if (r.notes.length) {
    lines.push("Замечания:");
    for (const n of r.notes.slice(0, NOTES_LIMIT)) lines.push(n.number ? `№ ${n.number}: ${n.text}` : n.text);
    if (r.notes.length > NOTES_LIMIT) lines.push(`… и ещё ${r.notes.length - NOTES_LIMIT}`);
  }
  if (r.errors.length) {
    lines.push("Не разобрано:");
    for (const e of r.errors) lines.push(`${e.file}: ${e.message}`);
  }
  if (r.open_issues > 0) lines.push(`Открытых вопросов: ${r.open_issues}.`);
  return lines.join("\n");
}

function show(option: unknown): string {
  if (Array.isArray(option)) return option.map(show).join("; ");
  if (option && typeof option === "object") return Object.values(option).map((v) => String(v).replace(/\n/g, " / ")).join(" | ");
  return String(option ?? "");
}

/** Все открытые вопросы одного акта — одним сообщением, по ряду кнопок на вопрос. */
export function actIssues(number: string, issues: Issue[]): Outgoing {
  if (!issues.length) return { text: `Акт № ${number}: вопросов не осталось.` };
  const lines = [`Акт № ${number} — вопросы (${issues.length}):`];
  const buttons: Button[][] = [];
  issues.forEach((q, i) => {
    const n = i + 1;
    if (q.kind === "conflict") {
      const fields = (q.fragments[0] ?? "").split(",").map((f) => fieldName(f.trim())).filter(Boolean).join(", ");
      lines.push(`${n}. Акт уже есть в реестре и отличается от скана (${fields}). Заменить данными из скана?`);
      buttons.push([{ label: `${n}: заменить`, data: `q:${q.id}:1` }, { label: `${n}: оставить`, data: `q:${q.id}:2` }]);
      return;
    }
    lines.push(`${n}. ${fieldName(q.field)}: прочитано по-разному.`);
    for (const k of [0, 1]) lines.push(`   ${k + 1}) ${q.fragments[k] ?? show(q.options[k])}`);
    const row = [{ label: `${n}: вариант 1`, data: `q:${q.id}:1` }, { label: `${n}: вариант 2`, data: `q:${q.id}:2` }];
    if (q.field !== "items" && q.field !== "appendices") row.push({ label: `${n}: напишу сам`, data: `q:${q.id}:own` });
    buttons.push(row);
  });
  return { text: lines.join("\n"), buttons };
}

export function registryCaption(e: { open_issues: number; issues_by_act: Record<string, number> }, total: number): string {
  const head = `Реестр: актов ${total}.`;
  if (!e.open_issues) return head;
  const acts = Object.keys(e.issues_by_act);
  const more = acts.length > LIST_LIMIT ? ` и ещё ${acts.length - LIST_LIMIT}` : "";
  return `${head}\nОткрытых вопросов: ${e.open_issues} (акты: ${acts.slice(0, LIST_LIMIT).join(", ")}${more}).`;
}

export function confirmQuestion(action: Action, id: string): Outgoing {
  if (action.kind === "delete") {
    return { text: `Удалить акт № ${action.number} вместе с приложениями?`,
      buttons: [[{ label: "Удалить", data: `c:${id}:yes` }, { label: "Отмена", data: `c:${id}:no` }]] };
  }
  if (action.kind === "undo") {
    return { text: `Отменить последнее изменение: «${action.label}»?`,
      buttons: [[{ label: "Отменить изменение", data: `c:${id}:yes` }, { label: "Не надо", data: `c:${id}:no` }]] };
  }
  throw new Error("для замены реестра вопрос строит replaceQuestion");
}

export function replaceQuestion(fileName: string, check: { missing: string[]; incoming_total: number }, currentTotal: number, id: string): Outgoing {
  const head = `«${fileName}» — это реестр: актов ${check.incoming_total} (сейчас в реестре ${currentTotal}). Сделать его текущим?`;
  const cancel = { label: "Отмена", data: `c:${id}:no` };
  if (!check.missing.length) return { text: head, buttons: [[{ label: "Заменить", data: `c:${id}:keep` }, cancel]] };
  const list = check.missing.slice(0, LIST_LIMIT).join(", ") + (check.missing.length > LIST_LIMIT ? "…" : "");
  return {
    text: `${head}\nВ нём нет актов, которые есть сейчас (${check.missing.length}): ${list}`,
    buttons: [[{ label: "Заменить, эти акты оставить", data: `c:${id}:keep` }], [{ label: "Заменить, эти акты удалить", data: `c:${id}:drop` }], [cancel]],
  };
}

const CLAIM = /(?<![\p{L}])(удалил[аи]?|удал[её]н[аоы]?|отменил[аи]?|отмен[её]н[аоы]?|исправил[аи]?|исправлен[аоы]?|изменил[аи]?|измен[её]н[аоы]?|записал[аи]?|заменил[аи]?|замен[её]н[аоы]?)(?![\p{L}])/iu;

/** Модель иногда пишет «удалил», ничего не сделав. Если реестр в этом ходе не менялся — бот говорит это сам. */
export function factCheck(text: string, turn: { registryChanged: boolean; confirmations: number }): string | undefined {
  if (turn.registryChanged || !CLAIM.test(text)) return undefined;
  return "Уточнение от бота: в этом ходе реестр не менялся." + (turn.confirmations ? " Действие выполнится только после нажатия кнопки." : "");
}
