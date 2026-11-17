// Живая проверка агента: один привет и один вопрос с инструментом. Нужен ключ хаба.
import { mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { createPiAgent } from "../src/agent.js";
import { makeHome } from "../test/helpers.js";

const here = path.dirname(fileURLToPath(import.meta.url));
const { core } = await makeHome();
const stateDir = mkdtempSync(path.join(tmpdir(), "aosr-agent-"));
const cfg = { agentHome: path.join(here, "../agent-home"), stateDir, model: process.argv[2] ?? "qwen3.6-fp8-noreason" };
let agent = await createPiAgent(cfg, core);
const a = await agent.ask(1, "Привет, что ты умеешь? Запомни слово «шпунт».");
console.log("1:", a.text.slice(0, 300));
await agent.note(1, "обработан файл x.xlsx, добавлено 0 актов");
const b = await agent.ask(1, "Сколько актов в реестре?");
console.log("2:", b.text.slice(0, 300));
agent = await createPiAgent(cfg, core); // «перезапуск»
const c = await agent.ask(1, "Какое слово я просил запомнить и что сообщал бот про файл?");
console.log("3:", c.text.slice(0, 300));
process.exit(0);
