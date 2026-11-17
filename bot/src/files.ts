// Приём файла: проверка, сохранение во входящие, детерминированный конвейер ядра. Модель-агент здесь не участвует.
import { mkdirSync, writeFileSync } from "node:fs";
import path from "node:path";
import type { Agent } from "./agent.js";
import type { Confirmations } from "./confirm.js";
import { type Core, CoreError, INGEST_TIMEOUT_MS } from "./core.js";
import { actIssues, ingestReport, type IngestResult, type Issue, type Outgoing, replaceQuestion } from "./text.js";

export const MAX_FILE_BYTES = 20 * 1024 * 1024;
const EXTENSIONS = [".pdf", ".xlsx", ".xlsm"];
const NAME_LIMIT = 120;

export interface IncomingFile { fileId: string; name: string; size: number }
export interface FileDeps {
  core: Core; agent: Agent; confirmations: Confirmations;
  download(fileId: string): Promise<Buffer>;
  now?: () => Date;
}
export interface FileResult { messages: Outgoing[]; registryChanged: boolean }

/** Имя без каталогов и не длиннее 120 знаков; расширение сохраняется. */
export function safeName(name: string): string {
  const base = (name.split(/[/\\]/).pop() ?? "").replace(/[\u0000-\u001f]/g, "").trim();
  if (!base || /^\.+$/.test(base)) return "file";
  const ext = path.extname(base).slice(0, 10);
  return base.length <= NAME_LIMIT ? base : base.slice(0, base.length - ext.length).slice(0, NAME_LIMIT - ext.length) + ext;
}

function stamp(d: Date): string {
  const p = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}${p(d.getMonth() + 1)}${p(d.getDate())}-${p(d.getHours())}${p(d.getMinutes())}${p(d.getSeconds())}`;
}

/** Открытые вопросы по каждому акту из списка — по сообщению на акт. */
export async function issueMessages(core: Core, numbers: string[]): Promise<Outgoing[]> {
  const out: Outgoing[] = [];
  for (const number of [...new Set(numbers)]) {
    const { issues } = await core.run<{ issues: Issue[] }>(["issues", "--number", number]);
    if (issues.length) out.push(actIssues(number, issues));
  }
  return out;
}

export async function handleFile(deps: FileDeps, chatId: number, file: IncomingFile, progress: (text: string) => Promise<void>): Promise<FileResult> {
  const say = (text: string): FileResult => ({ messages: [{ text }], registryChanged: false });
  if (file.size > MAX_FILE_BYTES) {
    return say(`Файл «${file.name}» больше 20 МБ — Telegram не даёт боту такие скачивать. Пришлите первые две страницы акта отдельным PDF или сжатый скан.`);
  }
  if (!EXTENSIONS.includes(path.extname(file.name).toLowerCase())) {
    return say(`Не знаю, что делать с «${file.name}»: принимаю акты в xlsx и PDF и файл реестра.`);
  }
  const inbox = path.join(deps.core.home, "inbox");
  mkdirSync(inbox, { recursive: true });
  const saved = path.join(inbox, `${stamp((deps.now ?? (() => new Date()))())}_${safeName(file.name)}`);
  writeFileSync(saved, await deps.download(file.fileId));

  try {
    const { kind } = await deps.core.run<{ kind: string }>(["inspect", saved]);
    if (kind === "registry") {
      const check = await deps.core.run<{ missing: string[]; incoming_total: number }>(["replace-registry", saved, "--missing", "check"]);
      const { total } = await deps.core.run<{ total: number }>(["summary"]);
      const id = deps.confirmations.add(chatId, { kind: "replace", file: saved, fileName: file.name, missing: check.missing });
      return { messages: [replaceQuestion(file.name, check, total, id)], registryChanged: false };
    }
    if (kind !== "acts" && kind !== "scan") return say(`Не знаю, что делать с «${file.name}»: принимаю акты в xlsx и PDF и файл реестра.`);

    await progress(kind === "scan" ? `Принял «${file.name}», читаю скан двумя моделями, это около минуты…` : `Принял «${file.name}», разбираю…`);
    const r = await deps.core.run<IngestResult>(["ingest", saved], { timeoutMs: INGEST_TIMEOUT_MS });
    const report = ingestReport(file.name, r);
    const numbers = r.issues.map((q) => q.number);
    const questions = await issueMessages(deps.core, numbers);
    const about = numbers.length ? `\nПользователю показаны кнопками вопросы по актам: ${[...new Set(numbers)].join(", ")}.` : "";
    await deps.agent.note(chatId, `обработан файл. ${report}${about}`).catch(() => undefined);
    return { messages: [{ text: report }, ...questions], registryChanged: r.added.length + r.updated.length > 0 };
  } catch (e) {
    if (!(e instanceof CoreError)) throw e;
    return say(`Не получилось разобрать «${file.name}»: ${e.message}`);
  }
}
