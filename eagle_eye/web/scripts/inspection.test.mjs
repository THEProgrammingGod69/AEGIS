import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import ts from "typescript";

const source = await readFile(new URL("../src/lib/inspection.ts", import.meta.url), "utf8");
const code = ts.transpileModule(source, { compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ESNext } }).outputText;
const { safeInspection, safeRun, safeRunMeta, inspectionContext, approvalBlocker, reviewReason } = await import(`data:text/javascript;base64,${Buffer.from(code).toString("base64")}`);

function run(kind = "legacy", valid = undefined) {
  const it = { id: "LBL-PS11", check: "LABEL", result: "PASS", expected: "PS11", found: "PS11", target: "PS11",
    box: [0, 0, 20, 10], quad: [], conf: 0.9, marker: null, evidence: [] };
  return { engine_kind: kind, results: [it], registration: { targets: 20, anchors: 0, inliers: 0, valid },
    meta: { engine_kind: kind, counts: { PASS: 1, FAIL: 0, REVIEW: 0, SKIP: 0 }, items: 1,
      issues: [], verdict: { label: "PASS", headline: "PASS", detail: "" }, warnings: [] } };
}

test("historical zero-anchor demo results become one input blocker without mutating the stored record", () => {
  const p = run();
  p.results.push({ ...p.results[0], id: "LBL-PS12", result: "FAIL" });
  const safe = safeInspection(p);
  assert.deepEqual(safe.results.map((it) => it.result), ["REVIEW", "SKIP", "SKIP"]);
  assert.equal(safe.meta.counts.PASS, 0);
  assert.equal(safe.meta.counts.FAIL, 0);
  assert.equal(safe.meta.verdict.label, "REVIEW");
  assert.equal(p.results[0].result, "PASS");
  assert.equal(p.results[1].result, "FAIL");
});

test("valid demo results are preserved", () => {
  const p = run("legacy", true);
  p.registration.anchors = 16;
  p.registration.inliers = 16;
  assert.equal(safeInspection(p), p);
});

test("historical unlocalised real-cabinet results cannot remain verified", () => {
  const p = run("real");
  p.registration.localised = false;
  const safe = safeInspection(p);
  assert.equal(safe.meta.counts.PASS, 0);
  assert.equal(safe.results[0].id, "REG-DRAWING");
});

test("a valid real placement is preserved with three anchors", () => {
  const p = run("real", true);
  p.registration.localised = true;
  p.registration.anchors = 3;
  p.registration.inliers = 3;
  assert.equal(safeInspection(p), p);
});

test("already guarded results are not duplicated", () => {
  const p = safeInspection(run("legacy", false));
  assert.equal(safeInspection(p), p);
});

test("review explanations distinguish missing views and drawing failures", () => {
  assert.match(reviewReason({ result: "NOT_IN_VIEW", evidence: [] }), /required cabinet view/);
  assert.match(reviewReason({ id: "REG-DRAWING", result: "REVIEW", evidence: [] }), /drawing alignment/);
  assert.equal(reviewReason({ result: "REVIEW", hint: "Capture CB11 close up", evidence: [] }), "Capture CB11 close up");
});

test("a historical real PASS without coverage cannot approve a cabinet", () => {
  const p = run("real", true);
  assert.match(approvalBlocker(p), /no coverage evidence/);
  p.coverage = { verified: 10, total: 10, in_view: 10 };
  assert.match(approvalBlocker(p), /required checks/i);
});

test("complete approved real coverage is accepted but contradictory unresolved results block it", () => {
  const p = run("real", true);
  p.coverage = { verified: 10, total: 10, in_view: 10, complete: true, approval_allowed: true };
  assert.equal(approvalBlocker(p), null);
  p.meta.counts.NOT_IN_VIEW = 1;
  assert.match(approvalBlocker(p), /outside the view/);
  p.meta.counts.NOT_IN_VIEW = 0;
  p.meta.counts.REVIEW = 1;
  assert.match(approvalBlocker(p), /unresolved/);
});

test("an absent complete flag cannot approve historical coverage", () => {
  const p = run("real", true);
  p.coverage = { verified: 10, total: 10, in_view: 10, approval_allowed: true };
  assert.match(approvalBlocker(p), /required checks/i);
});

function realEvidence() {
  const p = run("real", true);
  p.registration.views = ["BACK"];
  p.results[0].view = "BACK";
  p.results[0].verified_by = ["OCR", "geometry"];
  p.coverage = { verified: 1, total: 1, in_view: 1, complete: true, approval_allowed: true, by_view: { BACK: { verified: 1, total: 1 } } };
  return p;
}

test("saved unanchored and wrong-view conclusions are reassessed without changing the archive", () => {
  const p = realEvidence();
  p.results[0].rule = "LABEL.read_not_anchored";
  const guarded = safeRun(p);
  assert.equal(guarded.results[0].result, "REVIEW");
  assert.equal(guarded.coverage.verified, 0);
  assert.equal(guarded.coverage.approval_allowed, false);
  assert.equal(guarded.meta.historical_guard, true);
  assert.equal(p.results[0].result, "PASS");
  assert.equal(p.coverage.by_view.BACK.verified, 1);
  delete p.results[0].rule;
  p.results[0].view = "LEFT";
  assert.equal(safeRun(p).results[0].result, "REVIEW");
});

test("model-only approval and model-promoted missing-part conclusions cannot survive a saved report read", () => {
  const p = realEvidence();
  p.results[0].verified_by = ["Claude"];
  assert.equal(safeRun(p).results[0].result, "REVIEW");
  p.results[0] = { ...p.results[0], verified_by: ["OCR", "geometry", "Claude"], result: "FAIL", check: "MISSING", candidate: "CANDIDATE_FAULT", strength: "strong" };
  assert.equal(safeRun(p).results[0].result, "REVIEW");
});

test("well-supported current real results retain their findings", () => {
  const p = realEvidence();
  assert.equal(safeRun(p), p);
});

test("metadata-only historical lists show the same one registration blocker", () => {
  const p = run();
  const meta = { ...p.meta, registration: p.registration };
  const guarded = safeRunMeta(meta);
  assert.equal(guarded.counts.PASS, 0);
  assert.equal(guarded.issues[0].id, "REG-DRAWING");
  assert.equal(guarded.historical_guard, true);
  assert.equal(meta.counts.PASS, 1);
});

test("a recheck restores its preset and engine, while a replacement GA clears the inherited preset", () => {
  const parent = { preset: "emerson", engine: "real" };
  assert.deepEqual(inspectionContext({}, parent), { preset: "emerson", engine: "real" });
  assert.deepEqual(inspectionContext({ ga: {} }, parent), { preset: undefined, engine: "auto" });
  assert.deepEqual(inspectionContext({ preset: "other" }, parent), { preset: "other", engine: "real" });
});

test("invalid real alignment clears stale approved coverage in the payload and metadata", () => {
  const p = realEvidence();
  p.registration.valid = false;
  p.meta.coverage = p.coverage;
  const guarded = safeRun(p);
  for (const c of [guarded.coverage, guarded.meta.coverage]) {
    assert.equal(c.verified, 0);
    assert.equal(c.ratio, 0);
    assert.equal(c.complete, false);
    assert.equal(c.approval_allowed, false);
    assert.equal(c.by_view.BACK.verified, 0);
  }
  assert.equal(p.coverage.approval_allowed, true);
  assert.equal(p.meta.coverage.by_view.BACK.verified, 1);
});
