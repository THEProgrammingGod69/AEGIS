import type { Coverage, Counts, Item, RunMeta, RunPayload } from "./types";

const historicalMessage = "This older run contained unregistered crop judgments. They are suppressed in this view. Run a new inspection with the matching drawing to regenerate verified exports.";

function coverageBlocker(counts: Counts, cov?: Coverage): string | null {
  if (!cov) return "This report has no coverage evidence. Run a new inspection to verify the required drawing checks before approval.";
  if (cov.complete !== true || cov.approval_allowed !== true || cov.total <= 0 || cov.verified < cov.total || counts.FAIL > 0 || counts.REVIEW > 0 || (counts.NOT_IN_VIEW ?? 0) > 0 || counts.SKIP > 0)
    return "Required drawing checks remain unresolved, outside the view, or disabled. Complete all required checks before approval.";
  return null;
}

function unverifiedCoverage(p: RunPayload): RunPayload {
  const old = p.coverage ?? p.meta.coverage;
  const coverage: Coverage = { ...old, verified: 0, total: old?.total ?? 0, in_view: 0, ratio: 0,
    complete: false, approval_allowed: false, unresolved: p.results.length,
    by_view: Object.fromEntries(Object.entries(old?.by_view ?? {}).map(([view, value]) => [view, { ...value, verified: 0 }])) };
  return { ...p, coverage, meta: { ...p.meta, coverage } };
}

/** History, analytics and review queues must use the same safety rules as the full report. */
export function safeRunMeta(m: RunMeta, coverage = m.coverage, registration = m.registration): RunMeta {
  const legacy = (m.engine_kind ?? "legacy") === "legacy";
  const invalid = registration?.valid === false || m.warnings?.some((w) => w.code === "weak_registration")
    || (legacy ? registration?.targets > 0 && registration?.anchors === 0 : registration?.localised === false);
  if (invalid) {
    const alreadyGuarded = m.counts.PASS === 0 && m.counts.FAIL === 0 && m.issues.some((it) => it.id === "REG-DRAWING");
    if (alreadyGuarded) return m;
    const reason = registration?.invalid_reason || "The photograph could not be reliably matched to this drawing. Verify the cabinet and drawing revision before inspecting again.";
    const items = alreadyGuarded ? m.items : m.items + (m.issues.some((it) => it.id === "REG-DRAWING") ? 0 : 1);
    return { ...m, historical_guard: true, registration: { ...registration, valid: false, invalid_reason: reason },
      counts: { PASS: 0, FAIL: 0, REVIEW: 1, SKIP: Math.max(0, items - 1 - (legacy ? 0 : m.counts.NOT_IN_VIEW ?? 0)), NOT_IN_VIEW: legacy ? 0 : m.counts.NOT_IN_VIEW ?? 0 }, items, recheck: null,
      issues: [{ id: "REG-DRAWING", result: "REVIEW", found: "Inspection blocked: drawing alignment unavailable", marker: 1 }],
      verdict: { label: "REVIEW", headline: "Inspection blocked · Check the photo and drawing", detail: reason },
      warnings: [...(m.warnings ?? []).filter((w) => w.code !== "historical_registration"), { code: "historical_registration", message: historicalMessage }],
    };
  }
  const blocker = !legacy && m.verdict.label === "PASS" ? coverageBlocker(m.counts, coverage) : null;
  return blocker ? { ...m, verdict: { label: "REVIEW", headline: "Inspection incomplete · Capture the remaining checks", detail: blocker } } : m;
}

/** Historical reports may predate the backend guard. Never present their unregistered crops as verified. */
export function safeInspection(p: RunPayload): RunPayload {
  const legacy = (p.engine_kind ?? p.meta.engine_kind ?? "legacy") === "legacy";
  const invalid = p.registration.valid === false || p.meta.warnings?.some((w) => w.code === "weak_registration")
    || (legacy ? p.registration.targets > 0 && p.registration.anchors === 0 : p.registration.localised === false);
  if (!invalid) return p;
  if (!p.results.some((it) => it.result === "PASS" || it.result === "FAIL") && p.results.some((it) => it.id === "REG-DRAWING")) return legacy ? p : unverifiedCoverage(p);
  const reason = p.registration.invalid_reason || "The photograph could not be reliably matched to this drawing. Verify the cabinet and drawing revision before inspecting again.";
  const results: Item[] = p.results.filter((it) => it.id !== "REG-DRAWING").map((it) => !legacy && it.result === "NOT_IN_VIEW" ? { ...it, marker: null, recheck: undefined } : ({
    ...it, result: "SKIP", found: "Not evaluated: drawing alignment unavailable", root_cause: "REG-DRAWING", marker: null,
    recheck: undefined, evidence: [...it.evidence, reason],
  }));
  results.unshift({ id: "REG-DRAWING", check: "REGISTRATION", target: "Photo and drawing", expected: "A matching cabinet drawing and reliable alignment",
    found: "Inspection blocked: drawing alignment unavailable", result: "REVIEW", box: [0, 0, 0, 0], conf: 0, evidence: [reason], quad: [], marker: 1, hint: reason });
  const unseen = results.filter((it) => it.result === "NOT_IN_VIEW").length;
  const guarded: RunPayload = { ...p, results, rectified: false, registration: { ...p.registration, valid: false, invalid_reason: reason }, meta: { ...p.meta,
    historical_guard: true, counts: { PASS: 0, FAIL: 0, REVIEW: 1, SKIP: results.length - 1 - unseen, NOT_IN_VIEW: unseen }, items: results.length, recheck: null,
    issues: [{ id: "REG-DRAWING", result: "REVIEW", found: results[0].found, marker: 1 }],
    verdict: { label: "REVIEW", headline: "Inspection blocked · Check the photo and drawing", detail: reason },
    warnings: [...(p.meta.warnings ?? []), { code: "historical_registration", message: historicalMessage }],
  } };
  return legacy ? guarded : unverifiedCoverage(guarded);
}

/** Non-mutating read boundary shared by every report consumer. Archived files stay untouched. */
export function safeRun(p: RunPayload): RunPayload {
  const safe = safeRealEvidence(safeInspection(p));
  const meta = safeRunMeta(safe.meta, safe.coverage ?? safe.meta.coverage, safe.registration);
  return meta === safe.meta ? safe : { ...safe, meta };
}

/** Keep saved browser reports consistent with the backend's conclusive-evidence rules. */
export function conclusiveEvidenceIssue(it: Item, reg: RunPayload["registration"]): string | null {
  if (it.result !== "PASS" && it.result !== "FAIL") return null;
  const rule = it.rule ?? "";
  if (rule.endsWith(".read_view_not_placed") || rule === "LABEL.read_not_anchored") return "This device was read without verifying its drawing position";
  if (["LABEL.partial_support", "MISSING.partial", "ORDER.ambiguous"].includes(rule)) return "A partial or ambiguous observation does not verify this check";
  const sources = new Set((it.verified_by ?? []).map((s) => s.trim().toLowerCase()));
  const local = sources.has("ocr") && sources.has("geometry");
  const model = ["claude", "agent", "llm", "vlm", "replay", "mock"].some((s) => sources.has(s));
  if (model && !local) return "A model-only verdict does not establish local visual verification";
  if (it.result === "FAIL" && it.candidate === "CANDIDATE_FAULT" && (it.check === "MISSING" || model && it.strength !== "strong")) return "Absence or weak candidate evidence cannot be confirmed by a model's confidence";
  if (reg.valid === false || reg.localised === false || (reg.valid !== true && reg.localised !== true)) return "No reliable registration was recorded for this photograph";
  const fits = (reg.fits ?? []).map((f) => f.view).filter(Boolean);
  const views = new Set(fits.length ? fits : reg.views ?? []);
  if (!it.view || !views.has(it.view)) return "This finding's drawing view was not placed in this photograph";
  return local ? null : "The report does not record both local OCR and geometry for this finding";
}

function safeRealEvidence(p: RunPayload): RunPayload {
  if ((p.engine_kind ?? p.meta.engine_kind) !== "real") return p;
  let changed = false;
  const rows = p.results.map((it) => {
    const reason = conclusiveEvidenceIssue(it, p.registration);
    if (!reason) return it;
    changed = true;
    return { ...it, result: "REVIEW" as const, found: `Unverified: ${it.found}`, verified_by: [], conf: 0,
      hint: "Review the local evidence and capture this drawing view with readable surrounding labels",
      evidence: [...it.evidence, reason], recheck: undefined, prev_result: undefined, prev_found: undefined };
  });
  const old = p.coverage ?? p.meta.coverage;
  if (!changed && old && old.complete !== undefined && old.approval_allowed !== undefined) return p;
  let marker = 0;
  const results = rows.map((it) => ({ ...it, marker: it.result === "FAIL" || it.result === "REVIEW" ? ++marker : null,
    recheck: undefined, prev_result: undefined, prev_found: undefined }));
  const verified = new Set(results.filter((it) => it.check === "LABEL" && (it.result === "PASS" || it.result === "FAIL")).map((it) => it.target)).size;
  const total = old?.total ?? 0;
  const by_view = Object.fromEntries(Object.entries(old?.by_view ?? {}).map(([view, value]) => [view, { ...value,
    verified: new Set(results.filter((it) => it.check === "LABEL" && it.view === view && (it.result === "PASS" || it.result === "FAIL")).map((it) => it.target)).size }]));
  const coverage: Coverage = { ...old, verified, total, in_view: old?.in_view ?? 0, ratio: total ? verified / total : 0,
    complete: false, approval_allowed: false, unresolved: results.filter((it) => it.result !== "PASS" && it.result !== "FAIL").length, by_view };
  const counts: Counts = { PASS: 0, FAIL: 0, REVIEW: 0, SKIP: 0, NOT_IN_VIEW: 0 };
  results.forEach((it) => { counts[it.result] = (counts[it.result] ?? 0) + 1; });
  return { ...p, results, coverage, meta: { ...p.meta, coverage, counts, recheck: null, historical_guard: true,
    issues: results.filter((it) => it.marker != null).map((it) => ({ id: it.id, result: it.result, found: it.found, marker: it.marker! })),
    verdict: { label: counts.FAIL ? "HOLD" : "REVIEW", headline: counts.FAIL ? "Hold · Confirmed defects remain" : "Inspection incomplete · Verify local evidence", detail: "Stored conclusions were reassessed using local OCR and per-view registration. Missing coverage or unverified model judgments cannot approve this cabinet." },
    warnings: [...(p.meta.warnings ?? []).filter((w) => w.code !== "historical_evidence"), { code: "historical_evidence", message: "Historical conclusions without sufficient local evidence were downgraded. Rerun inspection to regenerate verified exports." }],
  } };
}

export function inspectionContext(input: { ga?: unknown; preset?: string | null; engine?: "auto" | "legacy" | "real" }, parent?: { preset?: string; engine?: "legacy" | "real"; meta?: { engine_kind?: "legacy" | "real" } }) {
  const preset = input.ga ? undefined : input.preset ?? parent?.preset;
  const engine = input.engine ?? (input.ga ? "auto" : preset ? "real" : parent?.engine ?? parent?.meta?.engine_kind);
  return { preset, engine };
}

/** A historical PASS is not evidence of cabinet approval when coverage was never recorded. */
export function approvalBlocker(p: RunPayload): string | null {
  if (p.registration.valid === false || p.registration.localised === false) return p.registration.invalid_reason || "Drawing alignment is unavailable. Check the photograph and matching drawing before inspecting again.";
  if ((p.engine_kind ?? p.meta.engine_kind) !== "real") return null;
  return coverageBlocker(p.meta.counts, p.coverage ?? p.meta.coverage);
}

/** Lead with the actual blocker instead of assuming every review is a blurry photograph. */
export function reviewReason(it: Item): string {
  if (it.check === "REGISTRATION" || it.id === "REG-DRAWING") return "Check cabinet identity and drawing alignment";
  if (it.result === "NOT_IN_VIEW") return "Capture the required cabinet view";
  if (it.result === "REVIEW") return it.hint || (it.evidence.some((e) => /registr|alignment|localis|localiz/i.test(e))
    ? "Resolve drawing alignment before judging this item" : "Evidence is insufficient; inspect the crop or capture a clearer view");
  return "";
}
