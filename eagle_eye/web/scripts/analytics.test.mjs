import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import ts from "typescript";

const compile = (source) => ts.transpileModule(source, { compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ESNext } }).outputText;
const dataUrl = (code) => `data:text/javascript;base64,${Buffer.from(code).toString("base64")}`;
const { pareto, issueDims } = await import(dataUrl(compile(await readFile(new URL("../src/lib/assembly.ts", import.meta.url), "utf8"))));
const CAL = { engines: { demo: { maps: { PASS: [{ lo: 0.99, hi: 1, n: 98, k: 98, p: 0.99 }], FAIL: [{ lo: 0.8, hi: 0.9, n: 8, k: 8, p: 0.9 }], REVIEW: [{ lo: 0, hi: 0.5, n: 3, k: 0, p: 0.2 }] } },
  real: { measures: ["text"], maps: { PASS: [{ lo: 0.9, hi: 1.0001, n: 50, k: 49, p: 0.97 }] } } } };
const confSrc = compile(await readFile(new URL("../src/lib/confidence.ts", import.meta.url), "utf8"))
  .replace(/import CAL from "\.\.\/data\/calibration\.json";/, `const CAL = ${JSON.stringify(CAL)};`);
const { itemConfidence, photoConfidence, pct } = await import(dataUrl(confSrc));

const issue = (id, result = "FAIL", extra = {}) => ({ id, result, found: "", marker: 1, ...extra });
const run = (...issues) => ({ issues });

test("the Pareto ranks recurring FAILs and folds the tail into Other", () => {
  const metas = [
    run(issue("LBL-PS11", "FAIL", { family: "Power supply", area: "Power supply row", station: "Labelling" }), issue("GA-CB42", "REVIEW")),
    run(issue("LBL-PS11", "FAIL", { family: "Power supply", area: "Power supply row", station: "Labelling" }), issue("FER-X3:3")),
    run(issue("LBL-PS11", "FAIL", { family: "Power supply", area: "Power supply row", station: "Labelling" }), issue("FER-X3:3"), issue("COL-X3:7"),
      issue("GA-PS12"), issue("ORD-RAIL-1"), issue("LBL-1CBP03")),
  ];
  const { rows, total } = pareto(metas, "fault", null, 3);
  assert.equal(total, 9, "REVIEW is a referral, not a recurring fault");
  assert.deepEqual(rows.map((r) => [r.label, r.n]), [["LBL-PS11", 3], ["FER-X3:3", 2], ["COL-X3:7", 1], ["Other (3)", 3]]);
  assert.equal(rows.at(-1).cum, 1);
  assert.equal(rows[0].share, 3 / 9);
  assert.equal(rows[1].area, "Terminal strip X3");
  const byStation = pareto(metas, "station", null).rows;
  assert.equal(byStation[0].label, "Labelling");
  assert.equal(byStation[0].n, 4);
});

test("runs saved before the Pareto are placed from the demo drawing's rails and device kinds", () => {
  const base = { meta: { engine_kind: "legacy" }, rails: [{ name: "RAIL-1", tags: ["CB41", "CB42", "CB43", "CB44"] }],
    layout: [{ tag: "CB43", kind: "breaker" }, { tag: "PS12", kind: "psu" }, { tag: "1CBP03", kind: "baseplate" }] };
  assert.deepEqual(issueDims(issue("ORD-RAIL-1"), base), { check: "ORDER", target: "RAIL-1", family: "Circuit breaker", area: "Breaker rail (RAIL-1)", station: "Mounting (rail layout)" });
  assert.equal(issueDims(issue("GA-PS12"), base).area, "Power supply row");
  assert.equal(issueDims(issue("LBL-1CBP03"), base).family, "I/O baseplate");
  assert.equal(issueDims(issue("MISS-PS12"), null).family, "Power supply");
  assert.equal(issueDims(issue("MISS-PS12"), null).area, "Area not recorded");
});

test("item and photo confidence come from the calibration, stored values win", () => {
  const item = (id, result, conf, extra = {}) => ({ id, result, conf, ...extra });
  assert.equal(itemConfidence(item("A", "PASS", 1), "demo"), 0.99);
  assert.equal(itemConfidence(item("B", "FAIL", 0.85, { confidence: 0.7 }), "demo"), 0.7);
  assert.equal(itemConfidence(item("C", "REVIEW", 0.4), "demo"), 0.2);
  assert.equal(itemConfidence(item("D", "NOT_IN_VIEW", 1), "demo"), null);
  const p = { meta: {}, engine_kind: "legacy", results: [item("A", "PASS", 1), item("B", "FAIL", 0.85), item("C", "REVIEW", 0.4)] };
  const pc = photoConfidence(p);
  assert.equal(pc.decided, 2);
  assert.equal(pc.review, 1);
  assert.ok(Math.abs(pc.score - 0.945) < 1e-9);
  assert.equal(pc.lowest[0].id, "B");
  assert.equal(pct(0.999), ">99%");
});

test("a kind of measurement the calibration never saw gets no confidence (wire colours on the real cabinet)", () => {
  const colour = { id: "COL-CB12-2/PS12-L", check: "COLOUR", result: "PASS", conf: 0.95 };
  assert.equal(itemConfidence(colour, "real"), null);
  assert.equal(itemConfidence({ id: "LBL-PS11", check: "LABEL", result: "PASS", conf: 0.95 }, "real"), 0.97);
  assert.equal(itemConfidence(colour, "demo"), 0.99, "the demo calibration was fitted on its colour checks too");
});
