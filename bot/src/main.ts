// Запуск бота: настройки → ядро → агент → Telegram (long polling).
import { execFileSync } from "node:child_process";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { createPiAgent } from "./agent.js";
import { createBot } from "./bot.js";
import { DEFAULT_CONFIG_PATH, loadConfig, readToken } from "./config.js";
import { createCore } from "./core.js";

const here = path.dirname(fileURLToPath(import.meta.url));
const stamp = () => new Date().toISOString();
const log = (line: string) => console.log(`${stamp()} ${line}`);

async function main(): Promise<void> {
  const cfg = loadConfig(process.env.AOSR_BOT_CONFIG ?? DEFAULT_CONFIG_PATH);
  const token = readToken(cfg);
  const core = createCore({ python: cfg.python, home: cfg.home });
  const summary = await core.run<{ total: number; open_issues: number }>(["summary"]);
  const agent = await createPiAgent({ agentHome: path.join(here, "../agent-home"), stateDir: cfg.agentState, model: cfg.model }, core);
  const bot = createBot({ token, allowed: cfg.allowed, core, agent, registryName: cfg.registryName, log,
    logChatFile: path.join(cfg.agentState, "log-chat.json") });
  let commit = "?";
  try { commit = execFileSync("git", ["-C", here, "rev-parse", "--short", "HEAD"], { encoding: "utf8" }).trim(); } catch { /* не из репозитория */ }
  for (const signal of ["SIGTERM", "SIGINT"] as const) {
    process.once(signal, () => {
      log(`получен ${signal}, останавливаюсь`);
      bot.audit.post(`⏹ Бот остановлен (${signal}).`);
      void bot.audit.idle().then(() => bot.stop());
    });
  }
  await bot.api.setMyCommands([
    { command: "reestr", description: "прислать реестр" },
    { command: "voprosy", description: "открытые вопросы" },
    { command: "new", description: "начать разговор заново" },
    { command: "help", description: "что я умею" },
  ]);
  await bot.start({
    allowed_updates: ["message", "callback_query"],
    onStart: (me) => {
      log(`бот запущен: @${me.username}; актов в реестре ${summary.total}, открытых вопросов ${summary.open_issues}; разрешённых id: ${cfg.allowed.length}`);
      bot.audit.post(`▶️ Бот запущен, версия ${commit}. Актов в реестре ${summary.total}, открытых вопросов ${summary.open_issues}, разрешённых id: ${cfg.allowed.length}.`);
    },
  });
}

main().catch((e) => {
  console.error(`${stamp()} бот не запустился: ${e instanceof Error ? e.message : String(e)}`);
  process.exit(1);
});
