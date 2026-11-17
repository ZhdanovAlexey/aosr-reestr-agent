import { mkdtempSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import { expect, test } from "vitest";
import { loadConfig, readToken } from "../src/config.js";

const file = (o: object) => { const f = path.join(mkdtempSync(path.join(tmpdir(), "aosr-cfg-")), "config.json"); writeFileSync(f, JSON.stringify(o)); return f; };

test("loadConfig fills defaults and expands ~", () => {
  const c = loadConfig(file({ allowed: [1, 2], home: "~/data/home", python: "/p/python" }));
  expect(c.allowed).toEqual([1, 2]);
  expect(c.home).toBe(path.join(process.env.HOME!, "data/home"));
  expect(c.model).toBe("qwen3.6-fp8-noreason");
  expect(c.registryName).toBe("Реестр_ИД.xlsx");
});

test("loadConfig rejects an empty allow-list, a missing file and missing paths", () => {
  expect(() => loadConfig(file({ allowed: [], home: "/h", python: "/p" }))).toThrow(/allowed/);
  expect(() => loadConfig(file({ allowed: ["abc"], home: "/h", python: "/p" }))).toThrow(/allowed/);
  expect(() => loadConfig(file({ allowed: [1], python: "/p" }))).toThrow(/home/);
  expect(() => loadConfig("/nonexistent/config.json")).toThrow(/нет файла настроек/);
});

test("readToken prefers env, falls back to the command, and never echoes the token", () => {
  const cfg = { tokenCmd: "print-token" } as any;
  expect(readToken(cfg, { AOSR_BOT_TOKEN: " 1:AAA \n" }, () => { throw new Error("не должен вызываться"); })).toBe("1:AAA");
  expect(readToken(cfg, {}, (cmd) => { expect(cmd).toBe("print-token"); return "2:BBB\n"; })).toBe("2:BBB");
  expect(() => readToken({} as any, {}, () => "")).toThrow(/AOSR_BOT_TOKEN/);
  let message = "";
  try { readToken(cfg, {}, () => "мусор-вместо-токена-9:ZZZSECRET"); } catch (e) { message = (e as Error).message; }
  expect(message).toMatch(/не похож на токен/);
  expect(message).not.toContain("ZZZSECRET");
  expect(() => readToken(cfg, {}, () => { throw new Error("exit 44: 3:CCCSECRET"); })).toThrow(/^команда tokenCmd не выполнилась$/);
});
