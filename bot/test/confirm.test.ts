import { expect, test } from "vitest";
import { Confirmations } from "../src/confirm.js";

test("confirmation is single-use", () => {
  const c = new Confirmations();
  const id = c.add(1, { kind: "delete", number: "А/1" });
  expect(id).toMatch(/^[0-9a-f]{8}$/);
  expect(c.take(id, 1)).toEqual({ kind: "delete", number: "А/1" });
  expect(c.take(id, 1)).toBeUndefined();
});

test("confirmation is bound to its chat", () => {
  const c = new Confirmations();
  const id = c.add(1, { kind: "undo", label: "x" });
  expect(c.take(id, 2)).toBeUndefined();
  expect(c.take(id, 1)).toEqual({ kind: "undo", label: "x" });
});

test("confirmation expires in an hour", () => {
  let now = 1_000_000;
  const c = new Confirmations(() => now);
  const id = c.add(1, { kind: "delete", number: "А/1" });
  now += 3_600_001;
  expect(c.take(id, 1)).toBeUndefined();
});

test("unknown id", () => { expect(new Confirmations().take("deadbeef", 1)).toBeUndefined(); });
