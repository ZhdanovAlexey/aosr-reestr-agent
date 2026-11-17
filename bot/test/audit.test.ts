import { mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import { Api } from "grammy";
import { expect, test } from "vitest";
import { createAudit, LOG_LIMIT } from "../src/audit.js";

const GROUP = -100500;

function setup(file = path.join(mkdtempSync(path.join(tmpdir(), "aosr-audit-")), "log-chat.json")) {
  const api = new Api("1:T");
  const sent: { method: string; payload: any }[] = [];
  const failures: number[] = [];
  const logs: string[] = [];
  api.config.use(async (_prev, method, payload) => {
    const code = failures.shift();
    if (code) return { ok: false, error_code: code, description: "boom SECRET", parameters: { retry_after: 0 } } as any;
    sent.push({ method, payload });
    return { ok: true, result: { message_id: 1, chat: { id: GROUP, type: "supergroup" }, date: 0 } } as any;
  });
  const audit = createAudit(api, { file, log: (l) => logs.push(l), clean: (s) => s.split("SECRET").join("***"), retryPauseMs: 0 });
  return { api, audit, sent, failures, logs, file };
}

test("nothing is sent until a chat is bound", async () => {
  const s = setup();
  s.audit.post("привет");
  s.audit.copy(1, 2);
  await s.audit.idle();
  expect(s.sent).toEqual([]);
  expect(s.audit.chatId()).toBeUndefined();
});

test("binding survives a restart", async () => {
  const s = setup();
  s.audit.bind(GROUP);
  expect(setup(s.file).audit.chatId()).toBe(GROUP);
});

test("an ordinary entry is silent, an alarm is not; long text is cut", async () => {
  const s = setup();
  s.audit.bind(GROUP);
  s.audit.post("x".repeat(LOG_LIMIT + 500));
  s.audit.post("беда SECRET", { alarm: true });
  await s.audit.idle();
  expect(s.sent.map((m) => [m.payload.chat_id, m.payload.disable_notification])).toEqual([[GROUP, true], [GROUP, false]]);
  expect(s.sent[0].payload.text.length).toBeLessThanOrEqual(LOG_LIMIT);
  expect(s.sent[0].payload.text.endsWith("…")).toBe(true);
  expect(s.sent[1].payload.text).toBe("беда ***");
});

test("a file is copied into the log chat", async () => {
  const s = setup();
  s.audit.bind(GROUP);
  s.audit.copy(100, 77);
  await s.audit.idle();
  expect(s.sent).toEqual([{ method: "copyMessage", payload: { chat_id: GROUP, from_chat_id: 100, message_id: 77, disable_notification: true } }]);
});

test("429 is retried once; other failures are logged, not thrown", async () => {
  const s = setup();
  s.audit.bind(GROUP);
  s.failures.push(429);
  s.audit.post("первая");
  await s.audit.idle();
  expect(s.sent.map((m) => m.payload.text)).toEqual(["первая"]);
  s.failures.push(403);
  s.audit.post("вторая");
  s.audit.post("третья");
  await s.audit.idle();
  expect(s.sent.map((m) => m.payload.text)).toEqual(["первая", "третья"]);
  expect(s.logs).toHaveLength(1);
  expect(s.logs[0]).toContain("журнал");
  expect(s.logs[0]).not.toContain("SECRET");
});
