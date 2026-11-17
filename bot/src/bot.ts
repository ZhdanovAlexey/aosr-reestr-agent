// Telegram-бот: доступ по списку id, одна очередь на все действия, файлы — конвейером, текст — агенту,
// необратимое — только по кнопке.
import { Bot, type Context, GrammyError, InlineKeyboard, InputFile } from "grammy";
import type { UserFromGetMe } from "grammy/types";
import type { Agent } from "./agent.js";
import { type Audit, createAudit, cut } from "./audit.js";
import { type Action, Confirmations } from "./confirm.js";
import { type Core, CoreError } from "./core.js";
import { handleFile, issueMessages } from "./files.js";
import { actIssues, chunks, confirmQuestion, factCheck, fieldName, type Issue, type Outgoing, plain, registryCaption, replaceQuestion } from "./text.js";

export interface BotDeps {
  token: string;
  allowed: number[];
  core: Core;
  agent: Agent;
  registryName: string;
  download?: (fileId: string) => Promise<Buffer>;
  botInfo?: UserFromGetMe;
  log?: (line: string) => void;
  now?: () => number;
  /** Пауза перед повтором после ответа 429; по умолчанию — сколько просит Telegram. */
  retryPauseMs?: number;
  /** Где хранится id группы журнала (привязывается командой /logs_here в группе). */
  logChatFile?: string;
}
export type AosrBot = Bot & { idle(): Promise<void>; audit: Audit };

export const HELP = `Я веду реестр исполнительной документации по актам скрытых работ.

Пришлите файлом:
- книгу с актами (xlsx) или скан акта (PDF, до 20 МБ) — внесу в реестр и пришлю его обратно;
- сам реестр, если правили его у себя, — после подтверждения сделаю его текущим.

Словами можно: найти или показать акт, исправить поле, удалить акт, отменить последнее изменение.
Удаление, отмену и замену реестра делаю только после нажатия кнопки.

Команды:
/reestr — прислать реестр
/voprosy — открытые вопросы
/new — начать разговор заново (реестр не трогается)
/cancel — передумал писать свой ответ на вопрос`;

const REPLACE_TIMEOUT_MS = 5 * 60_000;
const STALE = "Кнопка устарела. Повторите команду.";
const CLOSED = "Вопрос уже закрыт.";
const AWAIT_TTL_MS = 10 * 60_000;
const RETRIES = 3;

export function createBot(deps: BotDeps): AosrBot {
  const { core, agent } = deps;
  const log = deps.log ?? ((line: string) => console.error(line));
  const bot = new Bot(deps.token, deps.botInfo ? { botInfo: deps.botInfo } : undefined);
  const confirmations = new Confirmations();
  const now = deps.now ?? Date.now;
  const awaiting = new Map<number, { issue: string; number: string; field: string; at: number }>();
  const dirty = new Set<number>();
  const clean = (s: string) => s.split(deps.token).join("***");
  const audit = createAudit(bot.api, { file: deps.logChatFile, log, clean, retryPauseMs: deps.retryPauseMs });
  /** Запись журнала о действии, которое сейчас выполняется (очередь одна, значит и запись одна). */
  let entry: { lines: string[]; alarm: boolean } | undefined;
  const note = (line: string, alarm = false) => { if (entry) { entry.lines.push(line); entry.alarm ||= alarm; } };
  const names = new Map<number, string>();
  const who = (id: number) => `${names.get(id) ?? "?"} (${id})`;

  const download = deps.download ?? (async (fileId: string) => {
    const f = await bot.api.getFile(fileId);
    const res = await fetch(`https://api.telegram.org/file/bot${deps.token}/${f.file_path}`);
    if (!res.ok) throw new Error(`файл не скачался: HTTP ${res.status}`);
    return Buffer.from(await res.arrayBuffer());
  });

  // ---------- отправка ----------

  /** Вызов Telegram с повтором при 429: длинный список сообщений не должен оборваться на середине. */
  async function tg<T>(call: () => Promise<T>): Promise<T> {
    for (let attempt = 0; ; attempt++) {
      try {
        return await call();
      } catch (e) {
        if (!(e instanceof GrammyError) || e.error_code !== 429 || attempt >= RETRIES) throw e;
        await new Promise((r) => setTimeout(r, deps.retryPauseMs ?? (e.parameters?.retry_after ?? 1) * 1000 + 250));
      }
    }
  }

  const keyboard = (out: Outgoing) => {
    if (!out.buttons?.length) return undefined;
    return InlineKeyboard.from(out.buttons.map((row) => row.map((b) => InlineKeyboard.text(b.label, b.data))));
  };

  async function send(chatId: number, out: Outgoing): Promise<void> {
    const parts = chunks(out.text);
    for (const [i, part] of parts.entries()) {
      const last = i === parts.length - 1;
      await tg(() => bot.api.sendMessage(chatId, part, last ? { reply_markup: keyboard(out) } : {}));
    }
    const buttons = out.buttons?.flat().map((b) => `[${b.label}]`).join(" ");
    note(`🤖 ${cut(out.text, 700)}${buttons ? `\n   ${buttons}` : ""}`);
  }
  const say = (chatId: number, text: string) => send(chatId, { text });

  async function sendRegistry(chatId: number): Promise<void> {
    const e = await core.run<{ registry: string; open_issues: number; issues_by_act: Record<string, number> }>(["export"]);
    const { total } = await core.run<{ total: number }>(["summary"]);
    await tg(() => bot.api.sendDocument(chatId, new InputFile(e.registry, deps.registryName), { caption: registryCaption(e, total) }));
    audit.post(`📎 ${who(chatId)}: отправлен реестр, актов ${total}`);
  }

  // ---------- очередь ----------

  let tail: Promise<void> = Promise.resolve();
  let pending = 0;

  /** Поставить действие в очередь. Когда очередь опустела — один раз прислать реестр тем, у кого он менялся. */
  function enqueue(chatId: number, head: string, job: () => Promise<void>): void {
    pending++;
    tail = tail.then(async () => {
      entry = { lines: [`👤 ${who(chatId)} · ${head}`], alarm: false };
      const typing = setInterval(() => { bot.api.sendChatAction(chatId, "typing").catch(() => undefined); }, 4000);
      try {
        await job();
      } catch (e) {
        await report(chatId, e);
      } finally {
        clearInterval(typing);
        pending--;
        audit.post(entry.lines.join("\n"), { alarm: entry.alarm });
        entry = undefined;
      }
      if (pending === 0) {
        for (const id of [...dirty]) {
          dirty.delete(id);
          await sendRegistry(id).catch((e) => report(id, e));
        }
      }
    });
  }

  async function report(chatId: number, e: unknown): Promise<void> {
    try {
      if (e instanceof CoreError) {
        await say(chatId, `Не получилось: ${e.message}`);
      } else {
        log(clean(`ошибка в чате ${chatId}: ${e instanceof Error ? e.stack ?? e.message : String(e)}`));
        note(`❗ ошибка: ${cut(e instanceof Error ? e.stack ?? e.message : String(e), 1200)}`, true);
        await say(chatId, "Внутренняя ошибка, я записал её в журнал.");
      }
    } catch (e2) {
      log(clean(`не удалось сообщить об ошибке в чат ${chatId}: ${e2 instanceof Error ? e2.message : String(e2)}`));
    }
  }

  // ---------- доступ ----------

  bot.use(async (ctx, next) => {
    const id = ctx.from?.id;
    if (id !== undefined && ctx.from) names.set(id, [ctx.from.first_name, ctx.from.last_name].filter(Boolean).join(" "));
    if (ctx.chat && ctx.chat.type !== "private") {
      // в группах бот только пишет журнал; единственная команда — привязка группы разрешённым пользователем
      if (id !== undefined && deps.allowed.includes(id) && ctx.message?.text?.split(/[\s@]/)[0] === "/logs_here") {
        audit.bind(ctx.chat.id);
        await ctx.reply("Журнал работы бота буду писать в этот чат.");
      }
      return;
    }
    if (id !== undefined && deps.allowed.includes(id)) return next();
    if (ctx.message?.text?.split(/[\s@]/)[0] === "/start" && id !== undefined) {
      await ctx.reply(`Доступ к боту ограничен. Ваш id: ${id} — передайте его владельцу.`);
    }
    if (id !== undefined) audit.post(`⚠️ Чужой написал боту: ${who(id)}`, { alarm: true });
    log(`отброшено обновление от id ${id ?? "?"}: ${Object.keys(ctx.update).filter((k) => k !== "update_id").join(",")}`);
  });

  // ---------- команды ----------

  const command = (name: string, job: (chatId: number) => Promise<void>) =>
    bot.command(name, (ctx) => enqueue(ctx.chat.id, `команда /${name}`, () => job(ctx.chat.id)));

  command("start", (chat) => say(chat, HELP));
  command("help", (chat) => say(chat, HELP));
  command("reestr", async (chat) => { dirty.add(chat); });
  command("new", async (chat) => {
    awaiting.delete(chat);
    await agent.reset(chat);
    await say(chat, "Начал разговор заново. Реестр и вопросы на месте.");
  });
  command("cancel", async (chat) => {
    await say(chat, awaiting.delete(chat) ? "Хорошо, вопрос остаётся открытым." : "Сейчас я не жду ответа на вопрос.");
  });
  command("voprosy", async (chat) => {
    const { issues } = await core.run<{ issues: Issue[] }>(["issues"]);
    if (!issues.length) return say(chat, "Открытых вопросов нет.");
    for (const number of [...new Set(issues.map((q) => q.number))]) {
      await send(chat, actIssues(number, issues.filter((q) => q.number === number)));
    }
  });

  // ---------- файлы ----------

  bot.on("message:document", (ctx) => {
    const chat = ctx.chat.id;
    const d = ctx.message.document;
    audit.copy(chat, ctx.message.message_id);
    enqueue(chat, `файл «${d.file_name ?? "файл"}», ${Math.round((d.file_size ?? 0) / 1024)} КБ`, async () => {
      awaiting.delete(chat); // файл — новое дело: следующий текст уже не ответ на старый вопрос
      const r = await handleFile({ core, agent, confirmations, download }, chat,
        { fileId: d.file_id, name: d.file_name ?? "файл", size: d.file_size ?? 0 }, (t) => say(chat, t));
      for (const m of r.messages) await send(chat, m);
      if (r.registryChanged) dirty.add(chat);
    });
  });

  // ---------- текст ----------

  bot.on("message:text", (ctx) => {
    const chat = ctx.chat.id;
    const text = ctx.message.text;
    enqueue(chat, "текст", async () => {
      note(cut(text, 1000));
      if (text.startsWith("/")) return say(chat, HELP);
      const wait = awaiting.get(chat);
      if (wait && now() - wait.at > AWAIT_TTL_MS) {
        awaiting.delete(chat);
        await say(chat, `Я ждал ваш вариант ответа на вопрос по акту № ${wait.number}, но прошло больше 10 минут — вопрос остался открытым.`);
      } else if (wait) {
        return ownAnswer(chat, wait, text);
      }
      const reply = await agent.ask(chat, text);
      for (const c of reply.turn.calls ?? []) note(`⚙ ${c.name} ${cut(JSON.stringify(c.args), 300)} → ${cut(c.result, 300)}, ${c.ms} мс`);
      if (reply.failure) note(`❗ модель не ответила: ${cut(reply.failure, 600)}`, true);
      await say(chat, plain(reply.text));
      const fix = factCheck(reply.text, { registryChanged: reply.turn.registryChanged, confirmations: reply.turn.confirmations.length });
      if (fix) await say(chat, fix);
      for (const action of reply.turn.confirmations) {
        await send(chat, confirmQuestion(action, confirmations.add(chat, action)));
      }
      for (const m of await issueMessages(core, reply.turn.showIssuesFor)) await send(chat, m);
      if (reply.turn.registryChanged || reply.turn.sendRegistry) dirty.add(chat);
    });
  });

  async function ownAnswer(chat: number, wait: { issue: string; number: string; field: string }, text: string): Promise<void> {
    let r: { number: string; field: string; value: unknown };
    try {
      r = await core.run(["resolve", wait.issue, text.trim(), "--literal"]);
    } catch (e) {
      if (e instanceof CoreError && e.code === "issue_not_found") {
        awaiting.delete(chat);
        return say(chat, CLOSED);
      }
      if (e instanceof CoreError) return say(chat, `Не получилось: ${e.message}\nНапишите значение ещё раз или /cancel.`);
      throw e;
    }
    awaiting.delete(chat);
    dirty.add(chat);
    await say(chat, `Записал: ${fieldName(r.field)} = ${String(r.value)}.`);
    for (const m of await issueMessages(core, [r.number])) await send(chat, m);
    await agent.note(chat, `Пользователь сам ответил на вопрос ${wait.issue} по акту ${r.number}: ${fieldName(r.field)} = ${String(r.value)}`).catch(() => undefined);
  }

  // ---------- кнопки ----------

  bot.on("callback_query:data", async (ctx) => {
    const chat = ctx.chat?.id ?? ctx.from.id;
    const [kind, id, choice] = ctx.callbackQuery.data.split(":");
    // кнопке отвечаем сразу: работа может ждать в очереди за разбором скана
    await ctx.answerCallbackQuery().catch(() => undefined);
    enqueue(chat, `кнопка ${ctx.callbackQuery.data}`, async () => {
      const notice = kind === "q" ? await answerIssue(ctx, chat, id, choice) : kind === "c" ? await confirm(ctx, chat, id, choice) : STALE;
      if (notice) await say(chat, notice);
    });
  });

  // всё остальное (фото, голос, стикеры): молчание выглядело бы как поломка
  bot.on("message", (ctx) => enqueue(ctx.chat.id, "сообщение не текстом и не файлом", () =>
    say(ctx.chat.id, "Пришлите акт файлом (PDF или xlsx), а не фотографией: с фото я не работаю. Текстом можно задать вопрос по реестру.")));

  const edit = (ctx: Context, out: Outgoing) => {
    note(`✏️ ${cut(out.text, 700)}`);
    return tg(() => ctx.editMessageText(chunks(out.text)[0] ?? "", { reply_markup: keyboard(out) })).catch((e) => log(clean(`сообщение не обновилось: ${e?.message ?? e}`)));
  };

  async function answerIssue(ctx: Context, chat: number, id: string, choice: string): Promise<string | undefined> {
    if (choice === "own") {
      const { issues } = await core.run<{ issues: Issue[] }>(["issues"]);
      const q = issues.find((i) => i.id === id);
      if (!q) return CLOSED;
      awaiting.set(chat, { issue: q.id, number: q.number, field: q.field, at: now() });
      await say(chat, `Напишите значение для поля «${fieldName(q.field)}» акта № ${q.number} одним сообщением. /cancel — передумал.`);
      return undefined;
    }
    if (choice !== "1" && choice !== "2") return STALE;
    let r: { number: string; field: string; value: unknown };
    try {
      r = await core.run(["resolve", id, choice]);
    } catch (e) {
      if (e instanceof CoreError && e.code === "issue_not_found") return CLOSED;
      throw e;
    }
    if (awaiting.get(chat)?.issue === id) awaiting.delete(chat);
    dirty.add(chat);
    const { issues } = await core.run<{ issues: Issue[] }>(["issues", "--number", r.number]);
    await edit(ctx, actIssues(r.number, issues));
    await agent.note(chat, `Пользователь ответил кнопкой на вопрос ${id} по акту ${r.number}: ${fieldName(r.field)} = ${String(r.value)}`).catch(() => undefined);
    return undefined;
  }

  async function confirm(ctx: Context, chat: number, id: string, choice: string): Promise<string | undefined> {
    const action = confirmations.take(id, chat);
    if (!action) return STALE;
    if (choice === "no") {
      await edit(ctx, { text: "Отменено." });
      return undefined;
    }
    let done: string;
    try {
      if (action.kind === "replace" && (choice === "keep" || choice === "drop")) {
        // список «пропавших» актов показан при загрузке файла; если реестр с тех пор менялся — спрашиваем заново
        const check = await core.run<{ missing: string[]; incoming_total: number }>(["replace-registry", action.file, "--missing", "check"]);
        if ([...check.missing].sort().join("\n") !== [...action.missing].sort().join("\n")) {
          await edit(ctx, { text: "С тех пор реестр менялся — ничего не заменял. Вопрос задан заново." });
          const { total } = await core.run<{ total: number }>(["summary"]);
          const fresh = { ...action, missing: check.missing };
          await send(chat, replaceQuestion(action.fileName, check, total, confirmations.add(chat, fresh)));
          return undefined;
        }
      }
      done = await perform(action, choice);
    } catch (e) {
      if (!(e instanceof CoreError)) throw e;
      await edit(ctx, { text: `Не получилось: ${e.message}` });
      return undefined;
    }
    await edit(ctx, { text: done });
    if (!done.startsWith("С тех пор")) {
      dirty.add(chat);
      await agent.note(chat, `По кнопке пользователя выполнено: ${done}`).catch(() => undefined);
    }
    return undefined;
  }

  async function perform(action: Action, choice: string): Promise<string> {
    if (action.kind === "delete" && choice === "yes") {
      const r = await core.run<{ number: string }>(["delete", action.number]);
      return `Акт № ${r.number ?? action.number} удалён.`;
    }
    if (action.kind === "undo" && choice === "yes") {
      const { last_change } = await core.run<{ last_change: string | null }>(["summary"]);
      if (last_change !== action.label) return "С тех пор реестр менялся — ничего не отменял. Повторите команду.";
      const r = await core.run<{ undone: string }>(["undo"]);
      return `Отменено изменение: «${r.undone}».`;
    }
    if (action.kind === "replace" && (choice === "keep" || choice === "drop")) {
      const r = await core.run<{ total: number; kept: string[]; dropped: string[]; manual_edits: number; stray_rows?: number }>(
        ["replace-registry", action.file, "--missing", choice], { timeoutMs: REPLACE_TIMEOUT_MS });
      return `Реестр заменён: актов ${r.total}, оставлено ${r.kept.length}, удалено ${r.dropped.length}, перенесено ручных правок ${r.manual_edits}.`
        + (r.stray_rows ? ` Убрано строк без документа: ${r.stray_rows}.` : "");
    }
    throw new CoreError("bad_button", "кнопка не подходит к действию");
  }

  bot.catch((err) => log(clean(`ошибка обработчика: ${err.error instanceof Error ? err.error.message : String(err.error)}`)));

  return Object.assign(bot, {
    audit,
    async idle(): Promise<void> {
      let seen: Promise<void>;
      do { seen = tail; await seen; } while (seen !== tail);
      await audit.idle();
    },
  });
}
