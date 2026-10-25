/** Fault Forge, synthetic vs real (eval_gap.py): the same planted-fault scoring on generated cabinets and on photos of
 *  Emerson's real cabinet, side by side, in the evaluation catalogue's terms: confirmed (FAIL), referred (REVIEW),
 *  incorrect PASS, not assessed. Until real results exist, the real column can preview the layout with clearly
 *  labelled example numbers (never shown as measurements). */
import { motion } from "framer-motion";
import { FlaskConical } from "lucide-react";
import { useState } from "react";
import { api } from "../lib/api";
import { useAsync } from "../lib/hooks";
import type { ForgeGap as Gap, GapCategory, GapOutcome, GapRate, GapSide } from "../lib/types";

const pct = (v: number, d = 0) => `${(v * 100).toFixed(d)}%`;
const RATES: GapRate[] = ["fail_rate", "flag_rate", "incorrect_pass_rate", "false_fail_rate", "review_rate", "not_in_view_rate"];

const ROWS: { key: GapRate | "sec_per_photo"; label: string; note: string; higherIsBetter: boolean; fmt: (s: GapSide) => string }[] = [
  { key: "fail_rate", label: "Confirmed", note: "planted faults ending FAIL", higherIsBetter: true, fmt: (s) => pct(s.fail_rate) },
  { key: "flag_rate", label: "Flagged", note: "FAIL or REVIEW", higherIsBetter: true, fmt: (s) => pct(s.flag_rate) },
  { key: "incorrect_pass_rate", label: "Incorrect PASS", note: "planted faults cleared", higherIsBetter: false, fmt: (s) => pct(s.incorrect_pass_rate) },
  { key: "false_fail_rate", label: "False FAIL", note: "on correct items", higherIsBetter: false, fmt: (s) => `${s.false_fail} (${pct(s.false_fail_rate, 1)})` },
  { key: "review_rate", label: "Sent to REVIEW", note: "of correct items", higherIsBetter: false, fmt: (s) => pct(s.review_rate, 1) },
  { key: "not_in_view_rate", label: "Not in view", note: "of all items", higherIsBetter: false, fmt: (s) => pct(s.not_in_view_rate) },
  { key: "sec_per_photo", label: "Time per photo", note: "", higherIsBetter: false, fmt: (s) => (s.sec_per_photo == null ? "–" : `${s.sec_per_photo.toFixed(1)} s`) },
];

const OUTCOME: Record<GapOutcome, [string, string]> = {
  FAIL: ["Confirmed (FAIL)", "var(--pass)"],
  REVIEW: ["Referred (REVIEW)", "var(--review)"],
  PASS: ["Incorrect PASS", "var(--fail)"],
  unassessed: ["Not assessed", "var(--niv)"],
};

function cat(planted: number, FAIL: number, REVIEW: number, PASS: number): GapCategory {
  const unassessed = planted - FAIL - REVIEW - PASS;
  const r = (n: number) => (planted ? n / planted : 0);
  return { planted, FAIL, REVIEW, PASS, unassessed, fail_rate: r(FAIL), flag_rate: r(FAIL + REVIEW), incorrect_pass_rate: r(PASS) };
}

/** Made-up real-photo numbers that preview the layout. Shown only behind the "example data" banner. */
const EXAMPLE_CATS: Record<string, GapCategory> = {
  missing: cat(5, 0, 4, 0),
  wrong_label: cat(5, 3, 1, 0),
  swap: cat(5, 2, 2, 0),
  ferrule: cat(0, 0, 0, 0),
  colour: cat(0, 0, 0, 0),
};
const EXAMPLE_REAL: GapSide = {
  photos: 15, planted: 15, FAIL: 5, REVIEW: 7, PASS: 0, unassessed: 3,
  fail_rate: 5 / 15, flag_rate: 12 / 15, incorrect_pass_rate: 0,
  false_fail: 0, false_fail_rate: 0, review_rate: 0.12, not_in_view_rate: 0.35, judged: 300, sec_per_photo: 46,
  categories: EXAMPLE_CATS, engine: "real-cabinet engine", source: "example data, not measured",
  selection: "example data, not measured",
};

/** Real minus synthetic, in percentage points, coloured by whether real photos do worse or better. */
function Delta({ d, higherIsBetter }: { d: number | null | undefined; higherIsBetter: boolean }) {
  if (d == null) return <span className="tiny faint">–</span>;
  const pts = d * 100;
  if (Math.abs(pts) < 0.05) return <span className="mono small faint">0 pts</span>;
  const worse = higherIsBetter ? pts < 0 : pts > 0;
  return <span className={`mono small ${worse ? "gap-worse" : "gap-better"}`}>{pts > 0 ? "+" : ""}{pts.toFixed(1)} pts</span>;
}

function Split({ c, empty }: { c: GapCategory | null; empty: string }) {
  if (!c) return <span className="tiny faint">{empty}</span>;
  if (!c.planted) return <span className="tiny faint">not planted</span>;
  const w = (n: number) => `${(n / c.planted) * 100}%`;
  return (
    <div className="gap-split tip" data-tip={`${c.FAIL} confirmed · ${c.REVIEW} referred · ${c.PASS} incorrect PASS · ${c.unassessed} not assessed`}>
      <div className="gap-bar">
        <motion.i style={{ background: "var(--pass)" }} initial={{ width: 0 }} whileInView={{ width: w(c.FAIL) }} viewport={{ once: true }} transition={{ duration: 0.8 }} />
        <motion.i style={{ background: "var(--review-bar)" }} initial={{ width: 0 }} whileInView={{ width: w(c.REVIEW) }} viewport={{ once: true }} transition={{ duration: 0.8, delay: 0.1 }} />
        <motion.i style={{ background: "var(--fail)" }} initial={{ width: 0 }} whileInView={{ width: w(c.PASS) }} viewport={{ once: true }} transition={{ duration: 0.8, delay: 0.2 }} />
      </div>
      <span className="mono small">{c.FAIL}/{c.planted}</span>
    </div>
  );
}

function SideHead({ title, s, empty, example }: { title: string; s: GapSide | null; empty: string; example?: boolean }) {
  const render = s?.kind === "drawing_render";
  return (
    <div style={{ minWidth: 0 }}>
      <div className="mono tiny faint">
        {title}
        {example && <span className="gap-example-tag">EXAMPLE</span>}
        {render && <span className="gap-render-tag tip" data-tip="Images rendered from the real cabinet's GA drawing, not photographs">DRAWING RENDER</span>}
      </div>
      <div className="small">{s ? `${s.photos} ${render ? "renders" : "photos"} · ${s.planted} faults` : empty}</div>
    </div>
  );
}

function GapView({ g }: { g: Gap }) {
  const [example, setExample] = useState(false);
  const s = g.synthetic;
  const measured = g.real;
  const showExample = !measured && example;
  const r = measured ?? (showExample ? EXAMPLE_REAL : null);
  const gap: Partial<Record<GapRate, number>> | null = measured
    ? g.gap
    : showExample && s
      ? Object.fromEntries(RATES.map((k) => [k, EXAMPLE_REAL[k] - s[k]]))
      : null;
  const realCat = (id: string): GapCategory | null => (measured ? g.categories.find((c) => c.id === id)?.real ?? null : showExample ? EXAMPLE_CATS[id] ?? null : null);
  const realEmpty = "not measured yet";
  return (
    <div className="stack" style={{ ["--gap" as string]: "16px" }}>
      {!measured && (
        <div className={`card pad gap-notice${showExample ? " on" : ""}`}>
          <div className="small">
            {showExample
              ? <><b>Example data.</b> The real column shows made-up numbers that preview this comparison. They are not measurements of the engine.</>
              : <>The real column is not measured yet: Emerson's photos are not on this engine. Run the two commands below on a machine with <span className="mono">data/emerson/</span>.</>}
          </div>
          <button className="btn btn-sm" onClick={() => setExample(!example)}>
            <FlaskConical /> {showExample ? "Hide example data" : "Preview with example data"}
          </button>
        </div>
      )}

      <div className="card pad">
        <div className="gap-grid gap-head">
          <span className="card-title">Planted-fault comparison</span>
          <SideHead title="SYNTHETIC" s={s} empty="no self-test results" />
          <SideHead title="REAL" s={r} empty={realEmpty} example={showExample} />
          <span className="mono tiny faint">REAL − SYNTHETIC</span>
        </div>
        {ROWS.map((row) => (
          <div key={row.key} className="gap-grid gap-line">
            <span className="small">{row.label}{row.note && <span className="tiny faint"> · {row.note}</span>}</span>
            <span className="mono">{s ? row.fmt(s) : "–"}</span>
            <span className={`mono${showExample ? " gap-example-val" : ""}`}>{r ? row.fmt(r) : "–"}</span>
            {row.key === "sec_per_photo" ? <span /> : <Delta d={gap?.[row.key as GapRate]} higherIsBetter={row.higherIsBetter} />}
          </div>
        ))}
      </div>

      <div className="card pad">
        <div className="card-head">
          <div className="card-title">By fault type{showExample && <span className="gap-example-tag">EXAMPLE</span>}</div>
          <div className="legend tiny faint">
            <span><i className="gap-swatch" style={{ background: "var(--pass)" }} />confirmed (FAIL)</span>
            <span><i className="gap-swatch" style={{ background: "var(--review-bar)" }} />referred (REVIEW)</span>
            <span><i className="gap-swatch" style={{ background: "var(--fail)" }} />incorrect PASS</span>
            <span><i className="gap-swatch" style={{ background: "var(--line-3)" }} />not assessed</span>
          </div>
        </div>
        <div className="gap-grid gap-head">
          <span />
          <span className="mono tiny faint">SYNTHETIC</span>
          <span className="mono tiny faint">REAL{showExample && " (EXAMPLE)"}</span>
          <span className="mono tiny faint">CONFIRMED, GAP</span>
        </div>
        {g.categories.map((c) => {
          const rc = realCat(c.id);
          return (
            <div key={c.id} className="gap-grid gap-line">
              <span className="small">{c.label}</span>
              <Split c={c.synthetic} empty="no self-test results" />
              <Split c={rc} empty={realEmpty} />
              {c.synthetic?.planted && rc?.planted ? <Delta d={rc.fail_rate - c.synthetic.fail_rate} higherIsBetter /> : <span />}
            </div>
          );
        })}
      </div>

      {measured && g.real_rows.length > 0 && (
        <div className="card pad">
          <div className="card-title" style={{ marginBottom: 6 }}>{measured.kind === "drawing_render" ? "Real-cabinet renders" : "Real photos"} with a planted fault</div>
          {g.real_rows.flatMap((row) => row.faults.map((f, i) => (
            <div key={`${row.photo}-${i}`} className="gap-item">
              <span className="gap-dot" style={{ background: OUTCOME[f.outcome][1] === "var(--review)" ? "var(--review-bar)" : OUTCOME[f.outcome][1] }} />
              <span className="small grow ellipsis">{f.text ?? f.type}</span>
              <span className="tiny faint mono ellipsis">{row.photo}</span>
              <span className="tiny" style={{ color: OUTCOME[f.outcome][1] }}>{OUTCOME[f.outcome][0]}</span>
            </div>
          )))}
        </div>
      )}

      <div className="tiny muted">
        {s && <>Synthetic: {s.source}, {s.engine}, {s.selection}. </>}
        {measured && <>Real: {measured.source}; {measured.engine} {measured.agent === "off" ? "without" : "with"} the AI verifier; {measured.selection}. </>}
        {showExample && <>Real: example data, not measured. </>}
        Same terms as the evaluation comparison at the top of this page: only FAIL confirms a fault; REVIEW is a referral.
      </div>
      <div className="code"><span className="c"># measure the real side (Emerson's drawing set and photos in data/emerson/)</span>{"\n"}python forge_real.py{"\n"}python eval_gap.py</div>
    </div>
  );
}

export function ForgeGap() {
  const { data, error } = useAsync(api.forgeGap);
  if (error) return <div className="card pad small muted">{error}</div>;
  if (!data) return <div className="card pad small muted">Loading the synthetic vs real comparison…</div>;
  return <GapView g={data} />;
}
