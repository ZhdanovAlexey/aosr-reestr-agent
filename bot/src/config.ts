// Настройки бота (без секретов) и чтение токена. Токен не попадает ни в файлы, ни в тексты ошибок.
import { execSync } from "node:child_process";
import { existsSync, readFileSync } from "node:fs";
import { homedir } from "node:os";
import path from "node:path";

export interface Config {
  allowed: number[];
  home: string;
  python: string;
  model: string;
  registryName: string;
  agentState: string;
  tokenCmd?: string;
}

export const DEFAULT_CONFIG_PATH = path.join(homedir(), ".config", "aosr-bot", "config.json");
const expand = (p: string) => (p.startsWith("~/") ? path.join(homedir(), p.slice(2)) : p);

export function loadConfig(file: string): Config {
  if (!existsSync(file)) throw new Error(`нет файла настроек ${file}`);
  const raw = JSON.parse(readFileSync(file, "utf8"));
  const allowed = raw.allowed;
  if (!Array.isArray(allowed) || !allowed.length || !allowed.every((x) => Number.isSafeInteger(x))) {
    throw new Error(`${file}: allowed — непустой список числовых Telegram-id`);
  }
  for (const key of ["home", "python"]) {
    if (typeof raw[key] !== "string" || !raw[key]) throw new Error(`${file}: не задан путь ${key}`);
  }
  const home = expand(raw.home);
  return {
    allowed, home, python: expand(raw.python),
    model: raw.model ?? "qwen3.6-fp8-noreason",
    registryName: raw.registryName ?? "Реестр_ИД.xlsx",
    agentState: expand(raw.agentState ?? path.join(path.dirname(home), "agent")),
    tokenCmd: raw.tokenCmd,
  };
}

export function readToken(cfg: Pick<Config, "tokenCmd">, env: Record<string, string | undefined> = process.env,
  run: (cmd: string) => string = (cmd) => execSync(cmd, { encoding: "utf8", stdio: ["ignore", "pipe", "ignore"] })): string {
  let token = env.AOSR_BOT_TOKEN?.trim();
  if (!token) {
    if (!cfg.tokenCmd) throw new Error("нет токена бота: задайте AOSR_BOT_TOKEN или tokenCmd в настройках");
    try {
      token = run(cfg.tokenCmd).trim();
    } catch {
      throw new Error("команда tokenCmd не выполнилась");
    }
  }
  if (!/^\d+:\S+$/.test(token)) throw new Error("токен бота не похож на токен Telegram (ожидается вид 123456:ABC…)");
  return token;
}
