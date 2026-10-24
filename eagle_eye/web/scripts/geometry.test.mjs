import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import ts from "typescript";

const source = await readFile(new URL("../src/lib/geometry.ts", import.meta.url), "utf8");
const code = ts.transpileModule(source, { compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ESNext } }).outputText;
const { polygonBounds } = await import(`data:text/javascript;base64,${Buffer.from(code).toString("base64")}`);

test("unlocated blockers and malformed polygons cannot produce viewport bounds", () => {
  for (const p of [undefined, null, [], [[0, 0]], [[0, 0], [1, 1]], [[0, 0], [1, 0], [NaN, 2]], [[0, 0], [1, 0], [2, Infinity]], [[0, 0], [0, 0], [0, 0]]]) assert.equal(polygonBounds(p), null);
});

test("finite photo and transformed polygons retain usable bounds", () => {
  assert.deepEqual(polygonBounds([[10, 20], [30, 20], [30, 40], [10, 40]]), { x0: 10, y0: 20, x1: 30, y1: 40 });
  assert.deepEqual(polygonBounds([[-10, -20], [10, -20], [0, 10]]), { x0: -10, y0: -20, x1: 10, y1: 10 });
});
