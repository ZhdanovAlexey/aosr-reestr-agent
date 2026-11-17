// Инструменты агента — тонкие обёртки над командами ядра. Необратимое агент не выполняет: только просит кнопку.
import { defineTool, type ToolDefinition } from "@earendil-works/pi-coding-agent";
import { type TSchema, Type } from "typebox";
import type { Action } from "./confirm.js";
import { type Core, CoreError } from "./core.js";

/** Что бот должен сделать после ответа агента. */
export interface Turn {
  confirmations: Action[];
  registryChanged: boolean;
  sendRegistry: boolean;
  showIssuesFor: string[];
  /** Вызовы инструментов за ход — для журнала. */
  calls: ToolCall[];
}
export interface ToolCall { name: string; args: unknown; result: string; ms: number }

export const newTurn = (): Turn => ({ confirmations: [], registryChanged: false, sendRegistry: false, showIssuesFor: [], calls: [] });

export const TOOL_NAMES = ["find_acts", "show_act", "set_field", "delete_act", "restore_act", "list_issues", "resolve_issue",
  "undo_last_change", "registry_summary", "send_registry"] as const;

const FIND_LIMIT = 30;
const NEEDS_CONFIRMATION = { status: "needs_confirmation", message: "Пользователю показана кнопка. Действие пока НЕ выполнено." };
const fail = (code: string, message: string) => ({ ok: false, error: { code, message } });

export function buildTools(core: Core, turn: () => Turn): ToolDefinition[] {
  const tool = <S extends TSchema>(name: (typeof TOOL_NAMES)[number], label: string, description: string, parameters: S,
    run: (p: any) => Promise<object>) =>
    defineTool({
      name, label, description, parameters,
      async execute(_id: string, params: unknown) {
        let out: object;
        const started = Date.now();
        try {
          out = await run(params ?? {});
        } catch (e) {
          if (!(e instanceof CoreError)) throw e;
          out = fail(e.code, e.message);
        }
        const o = out as { error?: { code: string; message: string }; status?: string };
        turn().calls.push({ name, args: params ?? {}, ms: Date.now() - started,
          result: o.error ? `ошибка ${o.error.code}: ${o.error.message}` : o.status ?? "ok" });
        return { content: [{ type: "text" as const, text: JSON.stringify(out) }], details: undefined };
      },
    }) as unknown as ToolDefinition;

  const number = Type.String({ description: "Номер акта, например ВО/11-15/БО" });
  const none = Type.Object({});

  return [
    tool("find_acts", "Найти акты",
      "Найти акты в реестре. Все параметры необязательны; без параметров — все акты. number — номер акта или его часть. " +
      "text — слова из названия работ, места или приложений; сравнение идёт по основам слов, падеж не важен. " +
      "date_from и date_to — период по дате акта, ГГГГ-ММ-ДД. В ответе не больше 30 актов; count — сколько найдено всего.",
      Type.Object({ number: Type.Optional(Type.String()), text: Type.Optional(Type.String()),
        date_from: Type.Optional(Type.String()), date_to: Type.Optional(Type.String()) }),
      async (p) => {
        const args = ["find"];
        for (const [flag, v] of [["--number", p.number], ["--text", p.text], ["--from", p.date_from], ["--to", p.date_to]]) {
          if (v) args.push(flag, String(v));
        }
        const r = await core.run<{ acts: unknown[]; count: number }>(args);
        return r.acts.length > FIND_LIMIT ? { ok: true, acts: r.acts.slice(0, FIND_LIMIT), count: r.count, truncated: true } : { ok: true, ...r };
      }),
    tool("show_act", "Показать акт", "Показать один акт целиком: поля, приложения, открытые вопросы. Подходит и часть номера, если совпадение одно.",
      Type.Object({ number }), async (p) => ({ ok: true, ...(await core.run(["show", String(p.number)])) })),
    tool("set_field", "Исправить поле",
      "Исправить одно поле акта. Нужен точный номер акта. Поля: code (№ по ведомости), work (наименование работ), date (ДД.ММ.ГГГГ), " +
      "number (номер акта), unit (единица), qty (количество), place (место освидетельствования), appendix.N (строка приложения N; " +
      "пустое значение удаляет строку). Изменение выполняется сразу.",
      Type.Object({ number, field: Type.String(), value: Type.String() }),
      async (p) => {
        const r = await core.run(["set", String(p.number), String(p.field), String(p.value)]);
        turn().registryChanged = true;
        return { ok: true, ...r };
      }),
    tool("delete_act", "Удалить акт",
      "Попросить удалить акт вместе с приложениями. Сам инструмент ничего не удаляет: пользователю показывается кнопка подтверждения.",
      Type.Object({ number }),
      async (p) => {
        const r = await core.run<{ act: { number: string } }>(["show", String(p.number)]);
        const t = turn();
        if (!t.confirmations.some((a) => a.kind === "delete" && a.number === r.act.number)) t.confirmations.push({ kind: "delete", number: r.act.number });
        return { ...NEEDS_CONFIRMATION, number: r.act.number };
      }),
    tool("restore_act", "Вернуть удалённый акт",
      "Снять с акта отметку «удалён»: при следующей загрузке файла с этим актом он снова попадёт в реестр.",
      Type.Object({ number }), async (p) => ({ ok: true, ...(await core.run(["restore", String(p.number)])) })),
    tool("list_issues", "Открытые вопросы", "Открытые вопросы по реестру; number — только по одному акту.",
      Type.Object({ number: Type.Optional(Type.String()) }),
      async (p) => ({ ok: true, ...(await core.run(p.number ? ["issues", "--number", String(p.number)] : ["issues"])) })),
    tool("resolve_issue", "Ответить на вопрос",
      "Ответить на открытый вопрос. issue — id вопроса (например q3). answer — «1» или «2» (номер варианта) либо своё значение поля. " +
      "На вопрос о замене акта отвечает только пользователь кнопкой.",
      Type.Object({ issue: Type.String(), answer: Type.String() }),
      async (p) => {
        const { issues } = await core.run<{ issues: { id: string; number: string; kind: string }[] }>(["issues"]);
        const q = issues.find((i) => i.id === String(p.issue));
        if (!q) return fail("issue_not_found", `открытого вопроса «${p.issue}» нет`);
        const t = turn();
        if (q.kind === "conflict") {
          if (!t.showIssuesFor.includes(q.number)) t.showIssuesFor.push(q.number);
          return { status: "needs_button", message: "На этот вопрос отвечает пользователь кнопкой. Кнопки показаны. Ответ пока НЕ принят." };
        }
        const r = await core.run(["resolve", q.id, String(p.answer)]);
        t.registryChanged = true;
        return { ok: true, ...r };
      }),
    tool("undo_last_change", "Отменить последнее изменение",
      "Попросить отменить последнее изменение реестра. Сам инструмент ничего не отменяет: пользователю показывается кнопка подтверждения.",
      none,
      async () => {
        const s = await core.run<{ last_change: string | null }>(["summary"]);
        if (!s.last_change) return fail("nothing_to_undo", "отменять нечего: история изменений пуста");
        const t = turn();
        if (!t.confirmations.some((a) => a.kind === "undo")) t.confirmations.push({ kind: "undo", label: s.last_change });
        return { ...NEEDS_CONFIRMATION, last_change: s.last_change };
      }),
    tool("registry_summary", "Сводка реестра", "Сколько актов в реестре, за какой период, сколько открытых вопросов, какое изменение было последним.",
      none, async () => ({ ok: true, ...(await core.run(["summary"])) })),
    tool("send_registry", "Прислать реестр", "Прислать пользователю файл реестра. Файл отправит бот после твоего ответа.",
      none, async () => { turn().sendRegistry = true; return { ok: true, message: "Файл реестра будет отправлен после ответа." }; }),
  ];
}
