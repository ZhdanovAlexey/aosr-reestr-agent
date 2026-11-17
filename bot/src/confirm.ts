// Действия, которые выполняются только после нажатия кнопки. Хранятся в памяти: после перезапуска кнопки «устарели».
import { randomBytes } from "node:crypto";

export type Action =
  | { kind: "delete"; number: string }
  | { kind: "undo"; label: string }
  | { kind: "replace"; file: string; fileName: string; missing: string[] };

const TTL_MS = 3_600_000;

export class Confirmations {
  private items = new Map<string, { chatId: number; action: Action; at: number }>();

  constructor(private now: () => number = Date.now) {}

  add(chatId: number, action: Action): string {
    const id = randomBytes(4).toString("hex");
    this.items.set(id, { chatId, action, at: this.now() });
    return id;
  }

  /** Одноразово: повторное нажатие, чужой чат и запись старше часа дают undefined. */
  take(id: string, chatId: number): Action | undefined {
    const item = this.items.get(id);
    if (!item || item.chatId !== chatId) return undefined;
    this.items.delete(id);
    return this.now() - item.at > TTL_MS ? undefined : item.action;
  }
}
