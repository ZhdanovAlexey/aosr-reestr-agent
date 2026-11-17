import { expect, test } from "vitest";
import { CoreError, createCore, type Exec } from "../src/core.js";
import { makeHome } from "./helpers.js";

const ok = (o: object) => ({ stdout: JSON.stringify({ ok: true, ...o }) + "\n" });

test("returns command payload", async () => {
  const { core } = await makeHome();
  const r = await core.run(["summary"]);
  expect(r).toMatchObject({ total: 0, open_issues: 0, last_change: null });
  expect(r).not.toHaveProperty("ok");
});

test("core error carries code and message", async () => {
  const { core } = await makeHome();
  await expect(core.run(["show", "НЕТ/1"])).rejects.toMatchObject({ code: "act_not_found" });
  await expect(core.run(["show", "НЕТ/1"])).rejects.toBeInstanceOf(CoreError);
});

test("commands never overlap", async () => {
  let active = 0, max = 0;
  const done: string[] = [];
  const exec: Exec = async (_f, args) => {
    active++; max = Math.max(max, active);
    await new Promise((r) => setTimeout(r, args.at(-1) === "a" ? 30 : 5));
    active--; done.push(args.at(-1)!);
    return ok({});
  };
  const core = createCore({ python: "py", home: "/h", exec });
  await Promise.all([core.run(["a"]), core.run(["b"]), core.run(["c"])]);
  expect(max).toBe(1);
  expect(done).toEqual(["a", "b", "c"]);
});

test("passes home and arguments without a shell", async () => {
  let seen: string[] = [];
  const core = createCore({ python: "py", home: "/h", exec: async (_f, args) => { seen = args; return ok({}); } });
  await core.run(["set", "А/1; rm -rf /", "place", "x y"]);
  expect(seen).toEqual(["-m", "aosr", "--home", "/h", "set", "А/1; rm -rf /", "place", "x y"]);
});

test("garbage on stdout is internal_error", async () => {
  const core = createCore({ python: "py", home: "/h", exec: async () => ({ stdout: "Traceback (most recent call last)" }) });
  await expect(core.run(["summary"])).rejects.toMatchObject({ code: "internal_error" });
});

test("timeout frees the queue", async () => {
  let n = 0;
  const exec: Exec = async (_f, _a, opts) => {
    if (n++ === 0) throw Object.assign(new Error("killed"), { timedOut: true, timeoutMs: opts.timeoutMs });
    return ok({ total: 1 });
  };
  const core = createCore({ python: "py", home: "/h", exec });
  const first = core.run(["ingest", "x.pdf"], { timeoutMs: 1000 });
  const second = core.run(["summary"]);
  await expect(first).rejects.toMatchObject({ code: "timeout", message: "ядро не ответило за 1 с" });
  await expect(second).resolves.toEqual({ total: 1 });
});

test("failed command does not break the queue", async () => {
  const { core } = await makeHome();
  await expect(core.run(["undo"])).rejects.toMatchObject({ code: "nothing_to_undo" });
  await expect(core.run(["summary"])).resolves.toMatchObject({ total: 0 });
});
