import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import ts from "typescript";

const compile = (source) => ts.transpileModule(source, { compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ESNext } }).outputText;
const dataUrl = (code) => `data:text/javascript;base64,${Buffer.from(code).toString("base64")}`;
const format = dataUrl(compile(await readFile(new URL("../src/lib/format.ts", import.meta.url), "utf8")));
const fixes = compile(await readFile(new URL("../src/lib/fixes.ts", import.meta.url), "utf8")).replace('"./format"', JSON.stringify(format));
const { fixFor } = await import(dataUrl(fixes));
const photo = { engine_kind: "real", meta: {}, rails: [] };
const item = { id: "LBL-CB11", target: "CB11", check: "LABEL", result: "REVIEW", box: [800, 500, 90, 30], view: "BACK" };

test("real review instructions retain the actual hint and drawing view instead of inventing millimetres", () => {
  const f = fixFor({ ...item, hint: "Check drawing revision before capturing a label close-up" }, photo);
  assert.equal(f.detail, "Check drawing revision before capturing a label close-up");
  assert.match(f.where, /BACK/);
  assert.doesNotMatch(f.where, /mm/);
  assert.match(f.action, /Resolve evidence/);
});

test("unsupported documents require manual requirement review instead of a replacement photograph", () => {
  const f = fixFor({ ...item, id: "DOC-WIRELIST", target: "Uploaded wire list", rule: "COLOUR.unsupported_input" }, photo);
  assert.match(f.action, /manually/);
  assert.match(f.detail, /manual inspection/);
  assert.doesNotMatch(f.action, /photograph/i);
});
