// Вызов ядра: python -m aosr --home ПАПКА <команда>. Все вызовы идут строго по одному.
import { execFile } from "node:child_process";

export class CoreError extends Error {
  constructor(public code: string, message: string) {
    super(message);
    this.name = "CoreError";
  }
}

export type Exec = (file: string, args: string[], opts: { timeoutMs: number }) => Promise<{ stdout: string }>;

export interface Core {
  /** Возвращает ответ команды без поля ok; ok:false → CoreError с кодом ядра. */
  run<T = Record<string, unknown>>(args: string[], opts?: { timeoutMs?: number }): Promise<T>;
  readonly home: string;
}

export const DEFAULT_TIMEOUT_MS = 60_000;
export const INGEST_TIMEOUT_MS = 15 * 60_000;

/** Запуск без оболочки. Ненулевой код выхода — не ошибка: ядро и тогда печатает JSON. */
const defaultExec: Exec = (file, args, { timeoutMs }) =>
  new Promise((resolve, reject) => {
    execFile(file, args, { timeout: timeoutMs, killSignal: "SIGKILL", maxBuffer: 64 * 1024 * 1024 }, (err, stdout) => {
      if (err && (err.killed || err.signal)) reject(Object.assign(new Error("ядро остановлено"), { timedOut: true }));
      else if (err && !stdout) reject(new Error(`ядро не запустилось: ${(err as NodeJS.ErrnoException).code ?? err.message}`));
      else resolve({ stdout });
    });
  });

export function createCore(cfg: { python: string; home: string; exec?: Exec }): Core {
  const exec = cfg.exec ?? defaultExec;
  let tail: Promise<unknown> = Promise.resolve();

  async function call<T>(args: string[], timeoutMs: number): Promise<T> {
    let stdout: string;
    try {
      ({ stdout } = await exec(cfg.python, ["-m", "aosr", "--home", cfg.home, ...args], { timeoutMs }));
    } catch (e) {
      if ((e as { timedOut?: boolean }).timedOut) throw new CoreError("timeout", `ядро не ответило за ${Math.round(timeoutMs / 1000)} с`);
      throw new CoreError("internal_error", e instanceof Error ? e.message : String(e));
    }
    const line = stdout.trim().split("\n").at(-1) ?? "";
    let out: { ok?: boolean; error?: { code?: string; message?: string } } & Record<string, unknown>;
    try {
      out = JSON.parse(line);
    } catch {
      throw new CoreError("internal_error", `ядро ответило не JSON (команда ${args[0]})`);
    }
    if (out === null || typeof out !== "object" || out.ok !== true) {
      throw new CoreError(out?.error?.code ?? "internal_error", out?.error?.message ?? `команда ${args[0]} не выполнена`);
    }
    const { ok: _ok, ...rest } = out;
    return rest as T;
  }

  return {
    home: cfg.home,
    run<T>(args: string[], opts?: { timeoutMs?: number }): Promise<T> {
      const result = tail.then(() => call<T>(args, opts?.timeoutMs ?? DEFAULT_TIMEOUT_MS));
      tail = result.catch(() => undefined);
      return result;
    },
  };
}
