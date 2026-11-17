import { mkdtempSync, readdirSync, readFileSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import { expect, test } from "vitest";
import { Confirmations } from "../src/confirm.js";
import { CoreError } from "../src/core.js";
import { handleFile, MAX_FILE_BYTES, safeName } from "../src/files.js";
import { fakeAgent, fakeCore, type Reply } from "./helpers.js";

function setup(replies: Record<string, Reply>) {
  const home = mkdtempSync(path.join(tmpdir(), "aosr-files-"));
  const core = fakeCore(replies, home);
  const agent = fakeAgent();
  const confirmations = new Confirmations();
  const downloads: string[] = [];
  const progress: string[] = [];
  const deps = { core, agent, confirmations, now: () => new Date(2026, 10, 15, 9, 5, 7),
    download: async (id: string) => { downloads.push(id); return Buffer.from("данные"); } };
  const send = (name: string, size = 1000) => handleFile(deps, 7, { fileId: "f1", name, size }, async (t) => { progress.push(t); });
  return { home, core, agent, confirmations, downloads, progress, send };
}
const ingested = { added: ["А/1"], updated: [], total: 1, issues: [], open_issues: 0, notes: [], errors: [] };

test("oversized file is refused without download", async () => {
  const s = setup({});
  const r = await s.send("скан.pdf", MAX_FILE_BYTES + 1);
  expect(r).toEqual({ registryChanged: false, messages: [{ text: "Файл «скан.pdf» больше 20 МБ — Telegram не даёт боту такие скачивать. Пришлите первые две страницы акта отдельным PDF или сжатый скан." }] });
  expect([s.downloads, s.core.calls]).toEqual([[], []]);
});

test("unknown extension is refused without download", async () => {
  const s = setup({});
  const r = await s.send("фото.jpg");
  expect(r.messages).toEqual([{ text: "Не знаю, что делать с «фото.jpg»: принимаю акты в xlsx и PDF и файл реестра." }]);
  expect([s.downloads, s.core.calls]).toEqual([[], []]);
});

test("safeName keeps the file inside inbox", () => {
  expect(safeName("../../etc/passwd.xlsx")).toBe("passwd.xlsx");
  expect(safeName("a/b\\c.pdf")).toBe("c.pdf");
  expect(safeName("..")).toBe("file");
  expect(safeName("Акты ред формат №1.xlsx")).toBe("Акты ред формат №1.xlsx");
  const long = safeName("я".repeat(300) + ".xlsx");
  expect(long.length).toBeLessThanOrEqual(120);
  expect(long.endsWith(".xlsx")).toBe(true);
});

test("acts workbook goes through ingest and reports", async () => {
  const s = setup({ inspect: { kind: "acts" }, ingest: ingested });
  const r = await s.send("../Акты.xlsx");
  const saved = path.join(s.home, "inbox", "20261115-090507_Акты.xlsx");
  expect(readdirSync(path.join(s.home, "inbox"))).toEqual(["20261115-090507_Акты.xlsx"]);
  expect(readFileSync(saved, "utf8")).toBe("данные");
  expect(s.core.calls).toEqual([["inspect", saved], ["ingest", saved]]);
  expect(s.progress).toEqual(["Принял «../Акты.xlsx», разбираю…"]);
  expect(r).toEqual({ registryChanged: true, messages: [{ text: "«../Акты.xlsx»: добавлено 1, обновлено 0. Всего актов в реестре: 1." }] });
  expect(s.agent.notes).toHaveLength(1);
  expect(s.agent.notes[0]).toContain("добавлено 1");
});

test("scan with two questions on one act yields one question message", async () => {
  const qs = [
    { id: "q1", number: "ЗР/ВГ/1", kind: "mismatch", field: "qty", options: ["1", "2"], fragments: [] },
    { id: "q2", number: "ЗР/ВГ/1", kind: "mismatch", field: "appendix.2", options: ["а", "б"], fragments: ["а", "б"] }];
  const s = setup({ inspect: { kind: "scan" }, ingest: { ...ingested, added: ["ЗР/ВГ/1"], issues: qs, open_issues: 2 }, issues: { issues: qs, open: 2 } });
  const r = await s.send("скан.pdf");
  expect(s.progress).toEqual(["Принял «скан.pdf», читаю скан двумя моделями, это около минуты…"]);
  expect(r.messages).toHaveLength(2);
  expect(r.messages[1].text).toContain("Акт № ЗР/ВГ/1 — вопросы (2):");
  expect(r.messages[1].buttons).toHaveLength(2);
  expect(s.core.calls.at(-1)).toEqual(["issues", "--number", "ЗР/ВГ/1"]);
  expect(s.agent.notes[0]).toContain("ЗР/ВГ/1");
});

test("ingest with nothing added does not mark the registry changed", async () => {
  const s = setup({ inspect: { kind: "acts" }, ingest: { ...ingested, added: [], errors: [{ file: "a.xlsx", code: "bad_file", message: "нет листов с актами" }] } });
  expect((await s.send("a.xlsx")).registryChanged).toBe(false);
});

test("registry file asks before replacing and lists missing acts", async () => {
  const s = setup({ inspect: { kind: "registry" }, "replace-registry": { missing: ["А/1", "А/2"], incoming_total: 5 }, summary: { total: 7 } });
  const r = await s.send("Реестр.xlsx");
  expect(r.registryChanged).toBe(false);
  expect(r.messages).toHaveLength(1);
  expect(r.messages[0].text).toContain("актов 5 (сейчас в реестре 7)");
  expect(r.messages[0].buttons).toHaveLength(3);
  expect(s.core.calls.map((c) => c[0])).toEqual(["inspect", "replace-registry", "summary"]);
  expect(s.core.calls[1].slice(2)).toEqual(["--missing", "check"]);
  const id = r.messages[0].buttons![0][0].data.split(":")[1];
  expect(s.confirmations.take(id, 7)).toMatchObject({ kind: "replace", fileName: "Реестр.xlsx", missing: ["А/1", "А/2"] });
});

test("core timeout becomes a message, not an exception", async () => {
  const s = setup({ inspect: { kind: "scan" }, ingest: new CoreError("timeout", "ядро не ответило за 900 с") });
  const r = await s.send("скан.pdf");
  expect(r).toEqual({ registryChanged: false, messages: [{ text: "Не получилось разобрать «скан.pdf»: ядро не ответило за 900 с" }] });
  expect(s.agent.notes).toEqual([]);
});

test("ingest gets the long timeout", async () => {
  const s = setup({ inspect: { kind: "acts" }, ingest: ingested });
  const seen: (number | undefined)[] = [];
  const run = s.core.run.bind(s.core);
  s.core.run = ((args: string[], opts?: { timeoutMs?: number }) => { seen.push(opts?.timeoutMs); return run(args); }) as typeof s.core.run;
  await s.send("a.xlsx");
  expect(seen).toEqual([undefined, 15 * 60_000]);
});
