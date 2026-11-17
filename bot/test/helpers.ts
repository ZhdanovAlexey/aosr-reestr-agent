import { execFileSync } from "node:child_process";
import { mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { type Core, CoreError, createCore } from "../src/core.js";

const here = path.dirname(fileURLToPath(import.meta.url));
export const PYTHON = path.resolve(here, "../../.venv/bin/python");

/** Временная рабочая папка с пустым реестром из искусственного шаблона и настоящим ядром. */
export async function makeHome(): Promise<{ core: Core; home: string; template: string }> {
  const dir = mkdtempSync(path.join(tmpdir(), "aosr-bot-"));
  const template = path.join(dir, "template.xlsx");
  execFileSync(PYTHON, [path.join(here, "make_template.py"), template]);
  const home = path.join(dir, "home");
  const core = createCore({ python: PYTHON, home });
  await core.run(["init", "--template", template]);
  return { core, home, template };
}

export type Reply = unknown | CoreError | ((args: string[]) => unknown);

/** Подделка ядра: ответ выбирается по имени команды; все вызовы записываются. */
export function fakeCore(replies: Record<string, Reply>, home = "/tmp/fake-home"): Core & { calls: string[][] } {
  const calls: string[][] = [];
  return {
    home,
    calls,
    async run<T>(args: string[]): Promise<T> {
      calls.push(args);
      let r = replies[args[0]];
      if (typeof r === "function") r = (r as (a: string[]) => unknown)(args);
      if (r instanceof CoreError) throw r;
      if (r === undefined) throw new CoreError("internal_error", `подделка ядра не знает команду ${args[0]}`);
      return r as T;
    },
  };
}

import type { Agent, AgentReply } from "../src/agent.js";
import { newTurn } from "../src/tools.js";

/** Подделка агента: записывает вопросы и служебные сообщения, отвечает заданным. */
export function fakeAgent(reply: (text: string) => Partial<AgentReply> = () => ({})) {
  const asked: string[] = [], notes: string[] = [], resets: number[] = [];
  const agent: Agent = {
    async ask(_chat, text) { asked.push(text); return { text: "ответ агента", turn: newTurn(), ...reply(text) }; },
    async note(_chat, text) { notes.push(text); },
    async reset(chat) { resets.push(chat); },
  };
  return Object.assign(agent, { asked, notes, resets });
}
