// Журнал для людей: записи о работе бота в выбранную Telegram-группу. Сбой журнала никогда не ломает основную работу.
import { mkdirSync, readFileSync, renameSync, writeFileSync } from "node:fs";
import path from "node:path";
import { type Api, GrammyError } from "grammy";

export interface Audit {
  /** Id группы журнала; undefined — журнал в группу не ведётся. */
  chatId(): number | undefined;
  bind(id: number): void;
  /** Одна запись — одно сообщение. alarm — со звуком. */
  post(text: string, opts?: { alarm?: boolean }): void;
  /** Копия сообщения пользователя (файл) в группу журнала. */
  copy(fromChat: number, messageId: number): void;
  idle(): Promise<void>;
}
export interface AuditOptions {
  /** Где хранится id группы; без файла привязка живёт до перезапуска. */
  file?: string;
  log: (line: string) => void;
  clean: (text: string) => string;
  retryPauseMs?: number;
}

export const LOG_LIMIT = 3900;

/** Обрезать текст до n знаков, отметив обрезку многоточием. */
export const cut = (text: string, n: number) => (text.length > n ? `${text.slice(0, n - 1)}…` : text);

export function createAudit(api: Api, opts: AuditOptions): Audit {
  let chat: number | undefined;
  if (opts.file) {
    try {
      const saved = JSON.parse(readFileSync(opts.file, "utf8")).chat;
      if (Number.isSafeInteger(saved)) chat = saved;
    } catch { /* файла ещё нет */ }
  }
  let tail: Promise<void> = Promise.resolve();

  function queue(call: (chatId: number) => Promise<unknown>): void {
    const to = chat;
    if (to === undefined) return;
    tail = tail.then(async () => {
      try {
        try {
          await call(to);
        } catch (e) {
          if (!(e instanceof GrammyError) || e.error_code !== 429) throw e;
          await new Promise((r) => setTimeout(r, opts.retryPauseMs ?? (e.parameters?.retry_after ?? 1) * 1000 + 250));
          await call(to);
        }
      } catch (e) {
        opts.log(opts.clean(`запись в журнал группы не отправлена: ${e instanceof Error ? e.message : String(e)}`));
      }
    });
  }

  return {
    chatId: () => chat,
    bind(id) {
      chat = id;
      if (!opts.file) return;
      mkdirSync(path.dirname(opts.file), { recursive: true });
      writeFileSync(`${opts.file}.tmp`, JSON.stringify({ chat: id }));
      renameSync(`${opts.file}.tmp`, opts.file);
    },
    post(text, o) {
      const body = cut(opts.clean(text), LOG_LIMIT);
      queue((to) => api.sendMessage(to, body, { disable_notification: !o?.alarm }));
    },
    copy(fromChat, messageId) {
      queue((to) => api.copyMessage(to, fromChat, messageId, { disable_notification: true }));
    },
    async idle() {
      let seen: Promise<void>;
      do { seen = tail; await seen; } while (seen !== tail);
    },
  };
}
