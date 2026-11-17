import { expect, test } from "vitest";
import { CoreError } from "../src/core.js";
import { buildTools, newTurn, TOOL_NAMES } from "../src/tools.js";
import { fakeCore, type Reply } from "./helpers.js";

function setup(replies: Record<string, Reply>) {
  const core = fakeCore(replies);
  const turn = newTurn();
  const tools = buildTools(core, () => turn);
  const call = async (name: string, params: object = {}) => {
    const tool = tools.find((t) => t.name === name)!;
    const r = await (tool.execute as any)("id", params);
    return JSON.parse(r.content[0].text);
  };
  return { core, turn, call };
}
const act = { act: { number: "ВО/1", date: "2024-08-19", issues: [] } };

test("delete_act asks for confirmation and never calls core delete", async () => {
  const { core, turn, call } = setup({ show: act, delete: {} });
  const r = await call("delete_act", { number: "во/1" });
  expect(r.status).toBe("needs_confirmation");
  expect(core.calls).toEqual([["show", "во/1"]]);
  expect(turn.confirmations).toEqual([{ kind: "delete", number: "ВО/1" }]);
  expect(turn.registryChanged).toBe(false);
});

test("delete_act for a missing act returns the core error and no confirmation", async () => {
  const { turn, call } = setup({ show: new CoreError("act_not_found", "акта «Х/9» нет в реестре") });
  expect(await call("delete_act", { number: "Х/9" })).toEqual({ ok: false, error: { code: "act_not_found", message: "акта «Х/9» нет в реестре" } });
  expect(turn.confirmations).toEqual([]);
});

test("delete_act does not queue the same act twice", async () => {
  const { turn, call } = setup({ show: act });
  await call("delete_act", { number: "ВО/1" });
  await call("delete_act", { number: "ВО/1" });
  expect(turn.confirmations).toHaveLength(1);
});

test("undo_last_change never calls core undo", async () => {
  const { core, turn, call } = setup({ summary: { total: 3, last_change: "удалён акт А/1" }, undo: {} });
  expect((await call("undo_last_change")).status).toBe("needs_confirmation");
  expect(core.calls).toEqual([["summary"]]);
  expect(turn.confirmations).toEqual([{ kind: "undo", label: "удалён акт А/1" }]);
});

test("undo_last_change with empty history says nothing to undo", async () => {
  const { turn, call } = setup({ summary: { total: 0, last_change: null } });
  expect(await call("undo_last_change")).toEqual({ ok: false, error: { code: "nothing_to_undo", message: "отменять нечего: история изменений пуста" } });
  expect(turn.confirmations).toEqual([]);
});

const issues = { issues: [{ id: "q3", number: "А/1", kind: "mismatch", field: "qty" }, { id: "q4", number: "Б/2", kind: "conflict", field: "act" }], open: 2 };

test("resolve_issue refuses conflict issues and schedules buttons", async () => {
  const { core, turn, call } = setup({ issues, resolve: {} });
  expect((await call("resolve_issue", { issue: "q4", answer: "1" })).status).toBe("needs_button");
  expect(core.calls).toEqual([["issues"]]);
  expect(turn.showIssuesFor).toEqual(["Б/2"]);
  expect(turn.registryChanged).toBe(false);
});

test("resolve_issue answers a mismatch issue", async () => {
  const { core, turn, call } = setup({ issues, resolve: { issue: "q3", number: "А/1", field: "qty", value: "812,48" } });
  expect(await call("resolve_issue", { issue: "q3", answer: "2" })).toMatchObject({ ok: true, value: "812,48" });
  expect(core.calls).toEqual([["issues"], ["resolve", "q3", "2"]]);
  expect(turn.registryChanged).toBe(true);
});

test("resolve_issue for an unknown question", async () => {
  const { core, call } = setup({ issues });
  expect((await call("resolve_issue", { issue: "q99", answer: "1" })).error.code).toBe("issue_not_found");
  expect(core.calls).toEqual([["issues"]]);
});

test("find_acts caps the list at 30 and reports the full count", async () => {
  const acts = Array.from({ length: 64 }, (_, i) => ({ number: `А/${i}` }));
  const { core, call } = setup({ find: { acts, count: 64 } });
  const r = await call("find_acts", { text: "засыпка", date_from: "2024-08-01" });
  expect(core.calls).toEqual([["find", "--text", "засыпка", "--from", "2024-08-01"]]);
  expect([r.acts.length, r.count, r.truncated]).toEqual([30, 64, true]);
  expect((await setup({ find: { acts: acts.slice(0, 2), count: 2 } }).call("find_acts")).truncated).toBeUndefined();
});

test("set_field marks the registry as changed; a core error does not", async () => {
  const good = setup({ set: { number: "А/1", field: "place", old: "", new: "ПК 1" } });
  expect(await good.call("set_field", { number: "А/1", field: "place", value: "ПК 1" })).toMatchObject({ ok: true, new: "ПК 1" });
  expect(good.core.calls).toEqual([["set", "А/1", "place", "ПК 1"]]);
  expect(good.turn.registryChanged).toBe(true);
  const bad = setup({ set: new CoreError("bad_field", "неизвестное поле") });
  expect((await bad.call("set_field", { number: "А/1", field: "цвет", value: "x" })).ok).toBe(false);
  expect(bad.turn.registryChanged).toBe(false);
});

test("send_registry only raises the flag", async () => {
  const { core, turn, call } = setup({});
  expect((await call("send_registry")).ok).toBe(true);
  expect(turn.sendRegistry).toBe(true);
  expect(core.calls).toEqual([]);
});

test("read-only tools map to core commands", async () => {
  const { core, call } = setup({ show: act, issues, summary: { total: 1 }, restore: { number: "А/1" } });
  await call("show_act", { number: "А/1" });
  await call("list_issues", { number: "А/1" });
  await call("list_issues");
  await call("registry_summary");
  await call("restore_act", { number: "А/1" });
  expect(core.calls).toEqual([["show", "А/1"], ["issues", "--number", "А/1"], ["issues"], ["summary"], ["restore", "А/1"]]);
});

test("tool names are latin and there are exactly ten", () => {
  const { core } = setup({});
  const names = buildTools(core, newTurn).map((t) => t.name);
  expect(names).toEqual([...TOOL_NAMES]);
  expect(names).toHaveLength(10);
  for (const n of names) expect(n).toMatch(/^[a-z_]+$/);
  expect(names.some((n) => /bash|shell|exec|read|write|file/.test(n))).toBe(false);
});

test("every tool call is recorded in the turn with its outcome", async () => {
  const { turn, call } = setup({ show: act, set: new CoreError("bad_value", "дата не разобрана"), summary: { last_change: "удалён акт А/1" } });
  await call("show_act", { number: "ВО/1" });
  await call("set_field", { number: "ВО/1", field: "date", value: "вчера" });
  await call("undo_last_change");
  expect(turn.calls.map((c) => [c.name, c.args, c.result])).toEqual([
    ["show_act", { number: "ВО/1" }, "ok"],
    ["set_field", { number: "ВО/1", field: "date", value: "вчера" }, "ошибка bad_value: дата не разобрана"],
    ["undo_last_change", {}, "needs_confirmation"],
  ]);
  expect(turn.calls.every((c) => typeof c.ms === "number")).toBe(true);
});
