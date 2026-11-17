// Проба: pi SDK + локальная модель хаба + только свои инструменты. Одноразовый код.
import { createAgentSession, createExtensionRuntime, defineTool, ModelRuntime, type ResourceLoader, SessionManager, SettingsManager } from "@earendil-works/pi-coding-agent";
import { Type } from "typebox";
import { fileURLToPath } from "node:url";
import path from "node:path";

const here = path.dirname(fileURLToPath(import.meta.url));
const agentDir = path.join(here, "agent-home");
const modelId = process.argv[2] ?? "qwen3.8-27b";
const SYSTEM = "Ты помощник по реестру актов скрытых работ. Используй инструменты, не выдумывай данные, отвечай по-русски кратко. Сегодня 14.11.2026.";

type Call = { tool: string; args: unknown };

async function makeSession(calls: Call[], sessionManager = SessionManager.inMemory(here)) {
  const modelRuntime = await ModelRuntime.create({ authPath: path.join(agentDir, "auth.json"), modelsPath: path.join(agentDir, "models.json") });
  const model = modelRuntime.getModel("neuraldeep", modelId);
  if (!model) throw new Error("model not found: " + modelId);
  const text = (o: unknown) => ({ content: [{ type: "text" as const, text: JSON.stringify(o) }], details: undefined });
  const findActs = defineTool({
    name: "find_acts", label: "Найти акты",
    description: "Найти акты в реестре. Все параметры необязательны: number — номер акта или его часть; text — подстрока в названии работ; date_from/date_to — период по дате акта, ГГГГ-ММ-ДД.",
    parameters: Type.Object({ number: Type.Optional(Type.String()), text: Type.Optional(Type.String()), date_from: Type.Optional(Type.String()), date_to: Type.Optional(Type.String()) }),
    async execute(_id, params) {
      calls.push({ tool: "find_acts", args: params });
      return text({ count: 2, acts: [
        { number: "ВО/11-15/БО", date: "2024-08-19", work: "Устройство бетонного основания под колодцы 11-15", place: "11-15" },
        { number: "ВО/4-9/ОЗ", date: "2024-08-27", work: "Засыпка вручную траншей, пазух котлованов", place: "4-9" } ] });
    },
  });
  const deleteAct = defineTool({
    name: "delete_act", label: "Удалить акт",
    description: "Удалить акт из реестра по точному номеру. Удаление выполняется только после подтверждения пользователем кнопкой.",
    parameters: Type.Object({ number: Type.String() }),
    async execute(_id, params) { calls.push({ tool: "delete_act", args: params }); return text({ status: "needs_confirmation", message: "Пользователю показана кнопка подтверждения. Акт пока НЕ удалён." }); },
  });
  const resourceLoader: ResourceLoader = {
    getExtensions: () => ({ extensions: [], errors: [], runtime: createExtensionRuntime() }),
    getSkills: () => ({ skills: [], diagnostics: [] }), getPrompts: () => ({ prompts: [], diagnostics: [] }),
    getThemes: () => ({ themes: [], diagnostics: [] }), getAgentsFiles: () => ({ agentsFiles: [] }),
    getSystemPrompt: () => SYSTEM, getSystemPromptSource: () => undefined,
    getAppendSystemPrompt: () => [], getAppendSystemPromptSources: () => [], extendResources: () => {}, reload: async () => {},
  };
  const { session } = await createAgentSession({
    cwd: here, agentDir, model, thinkingLevel: "off", modelRuntime, resourceLoader,
    noTools: "builtin", customTools: [findActs, deleteAct], sessionManager,
    settingsManager: SettingsManager.inMemory({ compaction: { enabled: false }, retry: { enabled: true, maxRetries: 2 } }),
  });
  return session;
}

async function ask(utterance: string) {
  const calls: Call[] = [];
  const session = await makeSession(calls);
  try { await session.prompt(utterance); return { calls, tools: session.getActiveToolNames(), text: session.getLastAssistantText() ?? "" }; }
  finally { session.dispose(); }
}

const CASES: [string, (c: Call[], t: string) => boolean][] = [
  ["Какие акты были в августе 2024?", (c) => c.length === 1 && c[0].tool === "find_acts" && (c[0].args as any).date_from === "2024-08-01" && (c[0].args as any).date_to === "2024-08-31"],
  ["Найди акт ВО/11-15/БО", (c) => c.length >= 1 && c[0].tool === "find_acts" && (c[0].args as any).number === "ВО/11-15/БО"],
  ["Удали акт ВО/11-15/БО", (c, t) => c.some((x) => x.tool === "delete_act" && (x.args as any).number === "ВО/11-15/БО") && !/(успешно|был|уже) удал/i.test(t)],
  ["Привет, что ты умеешь?", (c) => c.length === 0],
  ["Есть акты по обратной засыпке?", (c) => c.length >= 1 && c[0].tool === "find_acts" && /засыпк/i.test((c[0].args as any).text ?? "")],
];

const mode = process.argv[3] ?? "cases";
if (mode === "cases") {
  let pass = 0, total = 0;
  for (const [u, ok] of CASES) {
    const runs = await Promise.all([0, 1, 2].map(() => ask(u).catch((e) => ({ calls: [] as Call[], tools: [], text: "ERROR " + e.message }))));
    for (const r of runs) { total++; const good = ok(r.calls, r.text) && r.text.trim().length > 0; if (good) pass++; console.log(JSON.stringify({ u, ok: good, calls: r.calls, text: r.text.slice(0, 200) })); }
  }
  console.log(`RESULT ${modelId}: ${pass}/${total}`);
} else if (mode === "builtin") {
  const r = await ask("Выполни команду ls в текущей папке и прочитай файл package.json");
  console.log(JSON.stringify({ activeTools: r.tools, calls: r.calls, text: r.text.slice(0, 300) }));
} else if (mode === "persist") {
  const dir = path.join(here, "sessions"); const calls: Call[] = [];
  const s1 = await makeSession(calls, SessionManager.create(here, dir));
  await s1.prompt("Запомни: кодовое слово — «шпунт». Ответь одним словом: ок."); const file = s1.sessionFile; s1.dispose();
  const s2 = await makeSession(calls, SessionManager.open(file!, dir));
  await s2.sendCustomMessage({ customType: "ingest_result", content: "Служебное сообщение от бота: обработан файл, добавлен акт ЗР/ВГ/1, открытых вопросов 2.", display: false, details: undefined }, { triggerTurn: false });
  await s2.prompt("Какое кодовое слово я называл? И что сообщил бот про последний файл?");
  console.log(JSON.stringify({ file, text: s2.getLastAssistantText() })); s2.dispose();
}
