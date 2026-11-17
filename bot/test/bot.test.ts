import { mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import { expect, test } from "vitest";
import type { AgentReply } from "../src/agent.js";
import { createBot } from "../src/bot.js";
import { CoreError } from "../src/core.js";
import { newTurn } from "../src/tools.js";
import { fakeAgent, fakeCore, type Reply } from "./helpers.js";

const OWNER = 100, STRANGER = 666, GROUP = -100777;
const TOKEN = "123456:SECRET-TOKEN-VALUE";
const botInfo = { id: 1, is_bot: true, first_name: "b", username: "aosr_test_bot", can_join_groups: false,
  can_read_all_group_messages: false, supports_inline_queries: false, can_connect_to_business: false, has_main_web_app: false } as any;

function setup(replies: Record<string, Reply> = {}, reply?: (text: string) => Partial<AgentReply>) {
  const core = fakeCore({ export: { registry: "/h/registry.xlsx", open_issues: 0, issues_by_act: {} }, summary: { total: 3, last_change: "удалён акт А/1" }, ...replies },
    mkdtempSync(path.join(tmpdir(), "aosr-bot-test-")));
  const agent = fakeAgent(reply);
  const sent: { method: string; payload: any }[] = [];
  const logs: string[] = [];
  const downloads: string[] = [];
  const clock = { now: 1_000_000 };
  const logChatFile = path.join(mkdtempSync(path.join(tmpdir(), "aosr-bot-log-")), "log-chat.json");
  const bot = createBot({ token: TOKEN, allowed: [OWNER], core, agent, registryName: "Реестр.xlsx", botInfo, log: (l) => logs.push(l), logChatFile,
    now: () => clock.now, retryPauseMs: 0,
    download: async (id) => { downloads.push(id); return Buffer.from("x"); } });
  let mid = 1000;
  const fail429: string[] = [];
  const deadChats: number[] = [];
  bot.api.config.use(async (_prev, method, payload) => {
    if (fail429.includes(method)) {
      fail429.splice(fail429.indexOf(method), 1);
      return { ok: false, error_code: 429, description: "Too Many Requests: retry after 0", parameters: { retry_after: 0 } } as any;
    }
    if (deadChats.includes((payload as any).chat_id)) return { ok: false, error_code: 403, description: "Forbidden: bot was kicked" } as any;
    sent.push({ method, payload });
    return { ok: true, result: method.startsWith("send") || method.startsWith("edit") ? { message_id: ++mid, chat: { id: OWNER, type: "private" }, date: 0 } : true } as any;
  });
  let uid = 0;
  const from = (id: number) => ({ id, is_bot: false, first_name: "u" });
  const chat = (id: number) => ({ id, type: "private" as const, first_name: "u" });
  const push = async (update: object) => { await bot.handleUpdate({ update_id: ++uid, ...update } as any); await bot.idle(); };
  const text = (t: string, id = OWNER) => push({ message: { message_id: ++mid, date: 0, from: from(id), chat: chat(id), text: t,
    ...(t.startsWith("/") ? { entities: [{ type: "bot_command", offset: 0, length: t.split(" ")[0].length }] } : {}) } });
  const doc = (name: string, size = 1000, id = OWNER) => ({ message: { message_id: ++mid, date: 0, from: from(id), chat: chat(id),
    document: { file_id: "f-" + name, file_unique_id: "u", file_name: name, file_size: size } } });
  const press = (data: string, id = OWNER, messageId = 555) => push({ callback_query: { id: "cb", from: from(id), chat_instance: "ci", data,
    message: { message_id: messageId, date: 0, chat: chat(id), text: "?" } } });
  const group = (t: string, id = OWNER) => push({ message: { message_id: ++mid, date: 0, from: from(id), chat: { id: GROUP, type: "supergroup", title: "g" }, text: t,
    ...(t.startsWith("/") ? { entities: [{ type: "bot_command", offset: 0, length: t.split(" ")[0].length }] } : {}) } });
  const toGroup = () => sent.filter((m) => m.payload.chat_id === GROUP);
  const toOwner = () => sent.filter((m) => m.method === "sendMessage" && m.payload.chat_id === OWNER).map((m) => m.payload.text as string);
  const texts = () => sent.filter((s) => s.method === "sendMessage").map((s) => s.payload.text as string);
  const of = (method: string) => sent.filter((s) => s.method === method);
  const buttonData = () => of("sendMessage").flatMap((s) => (s.payload.reply_markup?.inline_keyboard ?? []).flat().map((b: any) => b.callback_data as string));
  return { bot, core, agent, sent, logs, downloads, push, text, doc, press, texts, of, buttonData, clock, fail429, group, toGroup, toOwner, deadChats, logChatFile };
}
const withTurn = (t: Partial<ReturnType<typeof newTurn>>) => () => ({ turn: { ...newTurn(), ...t } });
const cmds = (s: { core: { calls: string[][] } }) => s.core.calls.map((c) => c[0]);

test("stranger gets only their id on /start; text, file and button are dropped", async () => {
  const s = setup({ delete: {} });
  await s.text("/start", STRANGER);
  expect(s.texts()).toEqual([`Доступ к боту ограничен. Ваш id: ${STRANGER} — передайте его владельцу.`]);
  await s.text("удали все акты", STRANGER);
  await s.push(s.doc("a.xlsx", 1000, STRANGER));
  await s.press("c:deadbeef:yes", STRANGER);
  await s.press("q:q1:1", STRANGER);
  expect(s.texts()).toHaveLength(1);
  expect([s.core.calls, s.agent.asked, s.downloads]).toEqual([[], [], []]);
  expect(s.logs.some((l) => l.includes(String(STRANGER)))).toBe(true);
});

test("text goes to the agent and the reply is sent as plain chunks", async () => {
  const s = setup({}, () => ({ text: "**Итог**\n" + "строка ответа\n".repeat(700) }));
  await s.text("что за август?");
  expect(s.agent.asked).toEqual(["что за август?"]);
  const out = s.of("sendMessage");
  expect(out.length).toBe(3);
  for (const m of out) {
    expect(m.payload.text.length).toBeLessThanOrEqual(4000);
    expect(m.payload.text).not.toContain("**");
    expect(m.payload.parse_mode).toBeUndefined();
  }
  expect(out.map((m) => m.payload.text).join("\n").match(/строка ответа/g)).toHaveLength(700);
  expect(s.of("sendDocument")).toEqual([]);
});

test("delete runs only after the button, and only once", async () => {
  const s = setup({ delete: { number: "ВО/1", removed_rows: 3 } }, withTurn({ confirmations: [{ kind: "delete", number: "ВО/1" }] }));
  await s.text("удали акт ВО/1");
  expect(s.texts()).toEqual(["ответ агента", "Удалить акт № ВО/1 вместе с приложениями?"]);
  expect(cmds(s)).not.toContain("delete");
  const yes = s.buttonData().find((d) => d.endsWith(":yes"))!;
  await s.press(yes);
  expect(s.core.calls.filter((c) => c[0] === "delete")).toEqual([["delete", "ВО/1"]]);
  expect(s.of("editMessageText").at(-1)!.payload.text).toBe("Акт № ВО/1 удалён.");
  expect(s.of("sendDocument")).toHaveLength(1);
  expect(s.agent.notes.at(-1)).toContain("Акт № ВО/1 удалён.");
  await s.press(yes);
  expect(s.core.calls.filter((c) => c[0] === "delete")).toHaveLength(1);
  expect(s.texts().at(-1)).toBe("Кнопка устарела. Повторите команду.");
  expect(s.of("sendDocument")).toHaveLength(1);
});

test("confirmation button from another chat or an unknown one is refused", async () => {
  const s = setup({ delete: {} });
  await s.press("c:deadbeef:yes");
  expect(cmds(s)).toEqual([]);
  expect(s.texts().at(-1)).toBe("Кнопка устарела. Повторите команду.");
});

test("declining a confirmation changes nothing", async () => {
  const s = setup({ delete: {} }, withTurn({ confirmations: [{ kind: "delete", number: "ВО/1" }] }));
  await s.text("удали акт ВО/1");
  await s.press(s.buttonData().find((d) => d.endsWith(":no"))!);
  expect(cmds(s)).not.toContain("delete");
  expect(s.of("editMessageText").at(-1)!.payload.text).toBe("Отменено.");
  expect(s.of("sendDocument")).toEqual([]);
});

test("undo runs only after the button", async () => {
  const s = setup({ undo: { undone: "удалён акт А/1" } }, withTurn({ confirmations: [{ kind: "undo", label: "удалён акт А/1" }] }));
  await s.text("отмени");
  expect(s.texts().at(-1)).toBe("Отменить последнее изменение: «удалён акт А/1»?");
  expect(cmds(s)).not.toContain("undo");
  await s.press(s.buttonData().find((d) => d.endsWith(":yes"))!);
  expect(cmds(s)).toContain("undo");
  expect(s.of("editMessageText").at(-1)!.payload.text).toBe("Отменено изменение: «удалён акт А/1».");
});

test("undo is refused if the registry changed after the question", async () => {
  const s = setup({ undo: {}, summary: { total: 3, last_change: "исправлено поле place акта Б/2" } },
    withTurn({ confirmations: [{ kind: "undo", label: "удалён акт А/1" }] }));
  await s.text("отмени");
  await s.press(s.buttonData().find((d) => d.endsWith(":yes"))!);
  expect(cmds(s)).not.toContain("undo");
  expect(s.of("editMessageText").at(-1)!.payload.text).toBe("С тех пор реестр менялся — ничего не отменял. Повторите команду.");
});

const q1 = { id: "q3", number: "А/1", kind: "mismatch", field: "qty", options: ["1", "2"], fragments: [] };
const q2 = { id: "q4", number: "А/1", kind: "mismatch", field: "place", options: ["x", "y"], fragments: [] };

test("answering a question edits the message to the remaining questions", async () => {
  const s = setup({ resolve: { issue: "q3", number: "А/1", field: "qty", value: "2" }, issues: { issues: [q2], open: 1 } });
  await s.press("q:q3:2", OWNER, 777);
  expect(s.core.calls.slice(0, 2)).toEqual([["resolve", "q3", "2"], ["issues", "--number", "А/1"]]);
  const edit = s.of("editMessageText").at(-1)!.payload;
  expect(edit.message_id).toBe(777);
  expect(edit.text).toContain("Акт № А/1 — вопросы (1):");
  expect(edit.reply_markup.inline_keyboard).toHaveLength(1);
  expect(s.of("sendDocument")).toHaveLength(1);
  expect(s.agent.notes.at(-1)).toContain("q3");
});

test("own answer: next text goes to resolve, not to the agent", async () => {
  const s = setup({ issues: (a: string[]) => (a.length > 1 ? { issues: [], open: 0 } : { issues: [q1, q2], open: 2 }),
    resolve: { issue: "q4", number: "А/1", field: "place", value: "ПК 1+00" } });
  await s.press("q:q4:own");
  expect(s.texts().at(-1)).toBe("Напишите значение для поля «место» акта № А/1 одним сообщением. /cancel — передумал.");
  await s.text("ПК 1+00");
  expect(s.agent.asked).toEqual([]);
  expect(s.core.calls).toContainEqual(["resolve", "q4", "ПК 1+00", "--literal"]);
  expect(s.texts()).toContain("Записал: место = ПК 1+00.");
  await s.text("спасибо");
  expect(s.agent.asked).toEqual(["спасибо"]);
});

test("/cancel leaves the question open", async () => {
  const s = setup({ issues: { issues: [q1], open: 1 }, resolve: {} });
  await s.press("q:q3:own");
  await s.text("/cancel");
  expect(s.texts().at(-1)).toBe("Хорошо, вопрос остаётся открытым.");
  await s.text("привет");
  expect(cmds(s)).not.toContain("resolve");
  expect(s.agent.asked).toEqual(["привет"]);
});

test("answering a closed question says so", async () => {
  const s = setup({ resolve: new CoreError("issue_not_found", "открытого вопроса «q3» нет") });
  await s.press("q:q3:1");
  expect(s.texts().at(-1)).toBe("Вопрос уже закрыт.");
  expect(s.of("sendDocument")).toEqual([]);
});

const ingested = { added: ["А/1"], updated: [], total: 1, issues: [], open_issues: 0, notes: [], errors: [] };

test("two files in a row produce one registry attachment", async () => {
  const s = setup({ inspect: { kind: "acts" }, ingest: ingested });
  await Promise.all([s.bot.handleUpdate({ update_id: 1, ...s.doc("a.xlsx") } as any), s.bot.handleUpdate({ update_id: 2, ...s.doc("b.xlsx") } as any)]);
  await s.bot.idle();
  expect(s.core.calls.filter((c) => c[0] === "ingest")).toHaveLength(2);
  expect(s.downloads).toEqual(["f-a.xlsx", "f-b.xlsx"]);
  const docs = s.of("sendDocument");
  expect(docs).toHaveLength(1);
  expect(docs[0].payload.caption).toBe("Реестр: актов 3.");
  expect(s.sent.at(-1)!.method).toBe("sendDocument");
});

test("oversized document is refused without download", async () => {
  const s = setup({});
  await s.push(s.doc("скан.pdf", 21 * 1024 * 1024));
  expect(s.texts()[0]).toContain("больше 20 МБ");
  expect([s.downloads, s.core.calls]).toEqual([[], []]);
});

test("registry is attached after a change made by the agent", async () => {
  const s = setup({}, withTurn({ registryChanged: true }));
  await s.text("поправь место");
  expect(s.of("sendDocument")).toHaveLength(1);
});

test("send_registry without changes attaches the registry; /reestr too", async () => {
  const s = setup({}, withTurn({ sendRegistry: true }));
  await s.text("пришли реестр");
  await s.text("/reestr");
  expect(s.of("sendDocument")).toHaveLength(2);
  expect(s.agent.asked).toEqual(["пришли реестр"]);
});

test("agent may ask the bot to show questions with buttons", async () => {
  const s = setup({ issues: { issues: [q1], open: 1 } }, withTurn({ showIssuesFor: ["А/1"] }));
  await s.text("в вопросе q9 замени");
  expect(s.texts().at(-1)).toContain("Акт № А/1 — вопросы (1):");
});

test("/voprosy lists questions per act or says there are none", async () => {
  const s = setup({ issues: { issues: [q1, { ...q2, number: "Б/2" }], open: 2 } });
  await s.text("/voprosy");
  expect(s.texts().map((t) => t.split("\n")[0])).toEqual(["Акт № А/1 — вопросы (1):", "Акт № Б/2 — вопросы (1):"]);
  const none = setup({ issues: { issues: [], open: 0 } });
  await none.text("/voprosy");
  expect(none.texts()).toEqual(["Открытых вопросов нет."]);
});

test("/new resets the conversation", async () => {
  const s = setup();
  await s.text("/new");
  expect(s.agent.resets).toEqual([OWNER]);
  expect(s.texts()).toEqual(["Начал разговор заново. Реестр и вопросы на месте."]);
});

test("replace reports rows dropped for having no document", async () => {
  const s = setup({ inspect: { kind: "registry" }, "replace-registry": (a: string[]) =>
    a[3] === "check" ? { missing: [], incoming_total: 1 } : { total: 1, kept: [], dropped: [], manual_edits: 0, stray_rows: 63 } });
  await s.push(s.doc("Шаблон.xlsx"));
  await s.press(s.buttonData().find((d) => d.endsWith(":keep"))!);
  expect(s.of("editMessageText").at(-1)!.payload.text).toBe(
    "Реестр заменён: актов 1, оставлено 0, удалено 0, перенесено ручных правок 0. Убрано строк без документа: 63.");
});

test("replace with 'drop' passes --missing drop", async () => {
  const s = setup({ inspect: { kind: "registry" }, "replace-registry": (a: string[]) =>
    a[3] === "check" ? { missing: ["А/1"], incoming_total: 2 } : { total: 2, kept: [], dropped: ["А/1"], manual_edits: 4 } });
  await s.push(s.doc("Реестр.xlsx"));
  await s.press(s.buttonData().find((d) => d.endsWith(":drop"))!);
  const last = s.core.calls.filter((c) => c[0] === "replace-registry").at(-1)!;
  expect(last.slice(2)).toEqual(["--missing", "drop"]);
  expect(s.of("editMessageText").at(-1)!.payload.text).toBe("Реестр заменён: актов 2, оставлено 0, удалено 1, перенесено ручных правок 4.");
  expect(s.of("sendDocument")).toHaveLength(1);
});

test("core error becomes a message and the queue goes on", async () => {
  const s = setup({ issues: new CoreError("no_registry", "в папке нет реестра") });
  await s.text("/voprosy");
  expect(s.texts()).toEqual(["Не получилось: в папке нет реестра"]);
  await s.text("привет");
  expect(s.texts().at(-1)).toBe("ответ агента");
});

test("an exception in a handler does not leak the token into logs or messages", async () => {
  const s = setup({}, () => { throw new Error(`сбой запроса https://api.telegram.org/bot${TOKEN}/sendMessage`); });
  await s.text("привет");
  expect(s.texts()).toEqual(["Внутренняя ошибка, я записал её в журнал."]);
  expect(s.logs.join("\n")).toContain("сбой запроса");
  expect(s.logs.join("\n")).not.toContain(TOKEN);
  await s.text("/new");
  expect(s.texts().at(-1)).toBe("Начал разговор заново. Реестр и вопросы на месте.");
});

test("/start and unknown commands show help", async () => {
  const s = setup();
  await s.text("/start");
  await s.text("/чтоэто");
  expect(s.texts()).toHaveLength(2);
  expect(s.texts()[0]).toContain("/reestr");
  expect(s.texts()[1]).toBe(s.texts()[0]);
  expect(s.agent.asked).toEqual([]);
});

test("a false claim of deletion gets a correction from the bot", async () => {
  const s = setup({}, () => ({ text: "Я удалил акты за август 2024 года." }));
  await s.text("удали все акты за август");
  expect(s.texts()).toEqual(["Я удалил акты за август 2024 года.", "Уточнение от бота: в этом ходе реестр не менялся."]);
  expect(s.of("sendDocument")).toEqual([]);
});

// ---------- находки независимой проверки ----------

const replaceReplies = (missingNow: string[]) => ({ inspect: { kind: "registry" }, "replace-registry": (() => {
  let checks = 0;
  return (a: string[]) => a[3] === "check"
    ? { missing: checks++ === 0 ? ["А/1"] : missingNow, incoming_total: 2 }
    : { total: 2, kept: [], dropped: ["А/1"], manual_edits: 0 };
})() });

test("replace is refused and re-asked if the set of missing acts changed after the question", async () => {
  const s = setup(replaceReplies(["А/1", "Б/2"]));
  await s.push(s.doc("Реестр.xlsx"));
  await s.press(s.buttonData().find((d) => d.endsWith(":drop"))!);
  const calls = s.core.calls.filter((c) => c[0] === "replace-registry").map((c) => c[3]);
  expect(calls).toEqual(["check", "check"]);
  expect(s.of("editMessageText").at(-1)!.payload.text).toBe("С тех пор реестр менялся — ничего не заменял. Вопрос задан заново.");
  expect(s.texts().at(-1)).toContain("В нём нет актов, которые есть сейчас (2): А/1, Б/2");
  expect(s.of("sendDocument")).toEqual([]);
  await s.press(s.buttonData().filter((d) => d.endsWith(":drop")).at(-1)!);
  expect(s.core.calls.filter((c) => c[0] === "replace-registry").at(-1)![3]).toBe("drop");
});

test("replace proceeds when the missing set is unchanged", async () => {
  const s = setup(replaceReplies(["А/1"]));
  await s.push(s.doc("Реестр.xlsx"));
  await s.press(s.buttonData().find((d) => d.endsWith(":keep"))!);
  expect(s.core.calls.filter((c) => c[0] === "replace-registry").map((c) => c[3])).toEqual(["check", "check", "keep"]);
});

test("a button press is acknowledged before the queued work runs", async () => {
  let release!: () => void;
  const gate = new Promise<void>((r) => { release = r; });
  const s = setup({ inspect: { kind: "acts" }, ingest: ingested }, undefined);
  const slow = s.core.run.bind(s.core);
  let started!: () => void;
  const ingestStarted = new Promise<void>((r) => { started = r; });
  s.core.run = (async (args: string[]) => { if (args[0] === "ingest") { started(); await gate; } return slow(args); }) as typeof s.core.run;
  await s.bot.handleUpdate({ update_id: 1, ...s.doc("a.xlsx") } as any);
  await ingestStarted; // разбор файла идёт и держит очередь
  await s.bot.handleUpdate({ update_id: 2, callback_query: { id: "cb", from: { id: OWNER, is_bot: false, first_name: "u" }, chat_instance: "ci",
    data: "c:deadbeef:yes", message: { message_id: 5, date: 0, chat: { id: OWNER, type: "private", first_name: "u" }, text: "?" } } } as any);
  expect(s.of("answerCallbackQuery")).toHaveLength(1);
  expect(s.texts()).not.toContain("Кнопка устарела. Повторите команду.");
  release();
  await s.bot.idle();
  expect(s.texts()).toContain("Кнопка устарела. Повторите команду.");
});

test("waiting for an own answer expires after ten minutes", async () => {
  const s = setup({ issues: { issues: [q1], open: 1 }, resolve: {} });
  await s.press("q:q3:own");
  s.clock.now += 10 * 60_000 + 1;
  await s.text("пришли реестр");
  expect(cmds(s)).not.toContain("resolve");
  expect(s.agent.asked).toEqual(["пришли реестр"]);
  expect(s.texts()).toContain("Я ждал ваш вариант ответа на вопрос по акту № А/1, но прошло больше 10 минут — вопрос остался открытым.");
});

test("a file cancels waiting for an own answer", async () => {
  const s = setup({ issues: { issues: [q1], open: 1 }, resolve: {}, inspect: { kind: "acts" }, ingest: ingested });
  await s.press("q:q3:own");
  await s.push(s.doc("a.xlsx"));
  await s.text("привет");
  expect(cmds(s)).not.toContain("resolve");
  expect(s.agent.asked).toEqual(["привет"]);
});

test("a photo or a voice message gets an explanation", async () => {
  const s = setup();
  await s.push({ message: { message_id: 9, date: 0, from: { id: OWNER, is_bot: false, first_name: "u" }, chat: { id: OWNER, type: "private", first_name: "u" },
    photo: [{ file_id: "p", file_unique_id: "u", width: 1, height: 1 }] } });
  expect(s.texts()).toEqual(["Пришлите акт файлом (PDF или xlsx), а не фотографией: с фото я не работаю. Текстом можно задать вопрос по реестру."]);
  expect([s.core.calls, s.agent.asked, s.downloads]).toEqual([[], [], []]);
});

test("a 429 from Telegram is retried, the list is not cut short", async () => {
  const s = setup({ issues: { issues: [q1, { ...q2, number: "Б/2" }, { ...q2, id: "q5", number: "В/3" }], open: 3 } });
  s.fail429.push("sendMessage", "sendMessage");
  await s.text("/voprosy");
  expect(s.texts().map((t) => t.split("\n")[0])).toEqual(["Акт № А/1 — вопросы (1):", "Акт № Б/2 — вопросы (1):", "Акт № В/3 — вопросы (1):"]);
});

test("a 429 on the registry file is retried", async () => {
  const s = setup();
  s.fail429.push("sendDocument");
  await s.text("/reestr");
  expect(s.of("sendDocument")).toHaveLength(1);
});

// ---------- группа журнала ----------

test("/logs_here binds the group for the owner only; other group messages are ignored", async () => {
  const s = setup();
  await s.group("/logs_here", STRANGER);
  await s.group("удали все акты");
  await s.group("/reestr");
  expect([s.sent, s.agent.asked, s.core.calls]).toEqual([[], [], []]);
  await s.group("/logs_here@aosr_test_bot");
  expect(s.toGroup().map((m) => m.payload.text)).toEqual(["Журнал работы бота буду писать в этот чат."]);
  expect(s.bot.audit.chatId()).toBe(GROUP);
});

test("an agent turn becomes one silent log entry: who, what, tool calls, replies", async () => {
  const s = setup({}, () => ({ text: "Нашёл два акта.", turn: { ...newTurn(), calls: [{ name: "find_acts", args: { text: "бетон" }, result: "ok", ms: 12 }] } }));
  await s.group("/logs_here");
  s.sent.length = 0;
  await s.text("найди бетон");
  expect(s.toOwner()).toEqual(["Нашёл два акта."]);
  const entries = s.toGroup();
  expect(entries).toHaveLength(1);
  expect(entries[0].payload.disable_notification).toBe(true);
  expect(entries[0].payload.text).toBe(
    `👤 u (${OWNER}) · текст\nнайди бетон\n⚙ find_acts {"text":"бетон"} → ok, 12 мс\n🤖 Нашёл два акта.`);
});

test("an incoming file is copied to the group and its report is logged", async () => {
  const s = setup({ inspect: { kind: "acts" }, ingest: { added: ["А/1"], updated: [], total: 3, notes: [], errors: [], issues: [] }, issues: { issues: [] } });
  await s.group("/logs_here");
  s.sent.length = 0;
  await s.push(s.doc("Акты.xlsx"));
  const g = s.toGroup();
  expect(g[0].method).toBe("copyMessage");
  expect(g[0].payload.from_chat_id).toBe(OWNER);
  const entry = g.find((m) => m.method === "sendMessage" && m.payload.text.startsWith("👤"))!;
  expect(entry.payload.text).toContain("файл «Акты.xlsx»");
  expect(entry.payload.text).toContain("🤖 Принял «Акты.xlsx», разбираю…");
  expect(g.at(-1)!.payload.text).toBe(`📎 u (${OWNER}): отправлен реестр, актов 3`);
});

test("an internal error is an alarm in the group and never shows the token", async () => {
  const s = setup({}, () => { throw new Error(`сеть упала ${TOKEN}`); });
  await s.group("/logs_here");
  s.sent.length = 0;
  await s.text("привет");
  const entry = s.toGroup().at(-1)!;
  expect(entry.payload.disable_notification).toBe(false);
  expect(entry.payload.text).toContain("❗");
  expect(entry.payload.text).toContain("сеть упала ***");
  expect(JSON.stringify(s.sent)).not.toContain(TOKEN);
});

test("a model failure is an alarm with the reason", async () => {
  const s = setup({}, () => ({ text: "Модель сейчас не отвечает.", failure: "503 upstream" }));
  await s.group("/logs_here");
  s.sent.length = 0;
  await s.text("привет");
  const entry = s.toGroup().at(-1)!;
  expect(entry.payload.disable_notification).toBe(false);
  expect(entry.payload.text).toContain("❗ модель не ответила: 503 upstream");
});

test("a stranger writing to the bot is an alarm", async () => {
  const s = setup();
  await s.group("/logs_here");
  s.sent.length = 0;
  await s.text("/start", STRANGER);
  const g = s.toGroup();
  expect(g).toHaveLength(1);
  expect(g[0].payload.disable_notification).toBe(false);
  expect(g[0].payload.text).toBe(`⚠️ Чужой написал боту: u (${STRANGER})`);
});

test("a dead log group does not break the answer to the user", async () => {
  const s = setup();
  await s.group("/logs_here");
  s.deadChats.push(GROUP);
  await s.text("привет");
  expect(s.toOwner()).toEqual(["ответ агента"]);
  expect(s.logs.some((l) => l.includes("журнал"))).toBe(true);
});
