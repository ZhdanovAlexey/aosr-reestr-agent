// Проверка перед установкой службы: настройки читаются, токен доступен. Печатает пути; токен не печатает.
import { existsSync } from "node:fs";
import { DEFAULT_CONFIG_PATH, loadConfig, readToken } from "./config.js";

try {
  const cfg = loadConfig(process.env.AOSR_BOT_CONFIG ?? DEFAULT_CONFIG_PATH);
  if (!existsSync(cfg.python)) throw new Error(`нет интерпретатора ${cfg.python} (python в настройках)`);
  readToken(cfg);
  console.log(JSON.stringify({ home: cfg.home, python: cfg.python }));
} catch (e) {
  console.error(e instanceof Error ? e.message : String(e));
  process.exit(1);
}
