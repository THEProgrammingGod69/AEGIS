import { Boxes, Cloud, Code2, Cpu, ExternalLink, FileCode2, Gauge, Network, Puzzle, ServerCog, Terminal, Wrench } from "lucide-react";
import { EngineLog } from "../components/motion";
import { Reveal } from "../components/ui";
import type { RunPayload } from "../lib/types";
import { STATIC, api } from "../lib/api";
import { useEngine } from "../lib/cloud";
import { REPO_URL } from "../lib/static";
import { useAsync } from "../lib/hooks";

const FILES = [
  ["inspector.py", "The engine: drawing parser, registration, the 5 plug-in checks, consensus and root-cause skip. Read this first."],
  ["ocr_capi.py", "In-process libtesseract (C API): the same OCR as the CLI, without a process start per crop. 5× faster."],
  ["service.py", "Run store: artefacts per run, re-check chains, proof crops, Fault Forge scoring, inspector reviews."],
  ["server.py", "FastAPI: the local console API (/api) and the stateless, streaming cloud API (/api/v2)."],
  ["report.py", "Marked-up photo, expected-vs-found crops, GA overlay, filled Excel checklist, re-check statuses."],
  ["pdf_report.py", "One-click PDF QC report: verdict, findings with proof, re-check table, full checklist."],
  ["render.py", "Photo generator + Fault Forge: plants faults and camera effects in test cabinets."],
  ["spec.py", "Builds the demo inputs: GA PDF, wire list, QC checklist (Emerson's example layout)."],
  ["eval_forge.py", "Self-test harness: python eval_forge.py 50 200."],
  ["app.py", "Streamlit version of the UI (lightweight fallback, same engine)."],
];

const API = [
  ["POST", "/api/inspect", "photo | sample, [ga, wires, checklist], [checks], [parent] → job"],
  ["GET", "/api/jobs/{id}", "live stage events, then run_id"],
  ["GET", "/api/runs/{id}", "verdict, every item with box + photo quad, drawing layout, anchors"],
  ["GET", "/api/runs/{id}/items/{item}/{expected|found|aligned}", "proof crops"],
  ["GET", "/api/runs/{id}/files/{pdf|checklist|json|marked}", "downloads"],
  ["POST", "/api/forge", "plant faults in an unseen cabinet, inspect, score"],
  ["POST", "/api/runs/{id}/review", "inspector decision on an item: PASS / FAIL / CLEAR, with note, who and when"],
  ["POST", "/api/v2/inspect", "stateless: streams progress, then the whole run (report, images, PDF, Excel) as NDJSON"],
  ["POST", "/api/v2/forge", "stateless Fault Forge: new cabinet, hidden faults, scored, streamed back"],
  ["GET", "/api/v2/diag/samples", "parity check: inspect the shipped samples on this engine and report counts"],
];

const TOOLS = ["Python", "OpenCV", "PyMuPDF", "Tesseract OCR", "NumPy", "openpyxl", "ReportLab", "FastAPI", "React", "GSAP", "Lenis", "Streamlit"];

type Line = { t: string; k: string; v: string; tone?: "pass" | "fail" | "review" | "accent" };

/** A recorded inspection, as the engine logged it, stage by stage. */
function runLog(p: RunPayload): Line[] {
  const t0 = new Date(p.meta.created).getTime() || Date.now();
  let acc = 0;
  const at = () => new Date(t0 + acc * 1000).toTimeString().slice(0, 8);
  const t = p.timing;
  const c = p.meta.counts;
  const r = p.registration;
  const out: Line[] = [];
  out.push({ t: at(), k: "parse_ga", v: `${p.layout.length} drawn items · ${p.meta.items} checks to run` });
  acc += t.parse;
  if (t.ocr != null) { out.push({ t: at(), k: "ocr", v: `labels read in ${t.ocr.toFixed(2)} s` }); acc += t.ocr; }
  out.push({ t: at(), k: "register", v: `${r.inliers}/${r.anchors} anchors · ${r.refined ? "homography" : "similarity"}${r.outliers.length ? ` · off-pattern ${r.outliers.join(", ")}` : ""}`, tone: "accent" });
  acc += t.register;
  for (const [k, sec] of Object.entries(t.checks)) {
    const rs = p.results.filter((x) => x.check === k);
    const f = rs.filter((x) => x.result === "FAIL").length;
    out.push({ t: at(), k: k.toLowerCase(), v: `${f} FAIL · ${rs.filter((x) => x.result === "PASS").length} PASS · ${sec.toFixed(2)} s`, tone: f ? "fail" : "pass" });
    acc += sec;
  }
  out.push({ t: at(), k: "consensus", v: `${c.FAIL} FAIL · ${c.REVIEW} REVIEW · ${c.SKIP} SKIP · ${c.PASS} PASS`, tone: c.FAIL ? "fail" : "pass" });
  out.push({ t: at(), k: "report", v: `${t.total.toFixed(1)} s total · PDF · checklist · proof crops`, tone: "accent" });
  return out;
}

export function Engine() {
  const sample = useAsync(async () => {
    const runs = await api.runs(80);
    const m = runs.find((x) => x.source !== "forge" && x.version === 1 && x.counts.FAIL > 0) ?? runs.find((x) => x.source !== "forge") ?? runs[0];
    return m ? api.run(m.id) : null;
  });
  const checks = useAsync(api.checks);
  const health = useAsync(api.health);
  const eng = useEngine();
  const h = STATIC && eng.health ? eng.health : health.data;
  return (
    <div className="main">
      <div className="page-head">
        <div>
          <span className="eyebrow">Engine</span>
          <h1>Plug-in checks on a drawing-anchored core.</h1>
          <p>Each check answers one narrow question about one expected item at one known spot. Adding a check (earthing, torque marks, cable ties…) is one new class; nothing else needs rewriting.</p>
        </div>
      </div>

      <div className="engine-checks">
        {checks.data?.map((c, i) => (
          <Reveal key={c.name} className="card pad check-card" delay={i * 0.05} data-spotlight="" data-tilt="6">
            <div className="row between">
              <span className="tag accent">@check("{c.name}")</span>
              <Puzzle size={16} className="faint" />
            </div>
            <h3>{c.title}</h3>
            <p className="check-q">“{c.question}”</p>
            <p className="tiny faint">{c.doc}</p>
          </Reveal>
        ))}
        <Reveal className="card pad check-card add" delay={0.25} data-spotlight="">
          <div className="row between">
            <span className="tag">@check("EARTH")</span>
            <Wrench size={16} className="faint" />
          </div>
          <h3>Your next check</h3>
          <p className="check-q">One class in inspector.py. It appears here, in the checklist, the PDF and the toggles automatically.</p>
        </Reveal>
      </div>

      <div className="engine-grid">
        <Reveal className="card pad">
          <div className="card-title" style={{ marginBottom: 14 }}><Code2 /> Adding a check</div>
          <div className="code">
            <span className="d">@check</span>(<span className="s">"EARTH"</span>){"\n"}
            <span className="k">class</span> <span className="f">EarthCheck</span>:{"\n"}
            {"    "}<span className="s">"""Earth bar has a conductor on every stud the drawing shows."""</span>{"\n"}
            {"    "}title = <span className="s">"Earth studs"</span>{"\n"}
            {"    "}<span className="k">def</span> <span className="f">run</span>(self, ctx):{"\n"}
            {"        "}out = []{"\n"}
            {"        "}<span className="k">for</span> d <span className="k">in</span> ctx.ga[<span className="s">"devices"</span>]:{"\n"}
            {"            "}<span className="k">if</span> d[<span className="s">"type"</span>] != <span className="s">"earth"</span>: <span className="k">continue</span>{"\n"}
            {"            "}occ = occupancy(ctx.rect, ctx.bpm, d[<span className="s">"box"</span>])   <span className="c"># known spot, narrow question</span>{"\n"}
            {"            "}r = <span className="s">"PASS"</span> <span className="k">if</span> occ &gt; <span className="d">0.6</span> <span className="k">else</span> <span className="s">"REVIEW"</span>   <span className="c"># unsure → REVIEW, never a guessed FAIL</span>{"\n"}
            {"            "}out.append(res(<span className="s">f"EARTH-</span>{"{"}d[<span className="s">'tag'</span>]{"}"}<span className="s">"</span>, <span className="s">"EARTH"</span>, d[<span className="s">"tag"</span>], ...)){"\n"}
            {"        "}<span className="k">return</span> out
          </div>
        </Reveal>
        <Reveal className="card pad" delay={0.06}>
          <div className="card-title" style={{ marginBottom: 14 }}>{STATIC ? <Cloud /> : <ServerCog />} {STATIC ? (eng.health ? "Cloud engine (live)" : "Recorded on") : "This machine"}</div>
          <div className="kv">
            <span>Engine</span><b className="mono">EAGLE EYE {h?.version ?? "…"}</b>
            <span>OCR</span><b className="mono" style={{ color: h ? (h.tesseract.ok ? "var(--pass)" : "var(--fail)") : undefined }}>{h ? h.tesseract.version ?? h.tesseract.error : "…"}</b>
            <span>OCR backend</span><b className="mono">{h?.tesseract.backend ?? "tesseract CLI"}</b>
            <span>OCR lanes</span><b className="mono">{h?.workers ?? "…"} parallel · {h?.cpu ?? "…"} CPU core{h?.cpu === 1 ? "" : "s"}</b>
            {STATIC && eng.health ? (
              <><span>Endpoint</span><b className="mono ellipsis" title={eng.url}>{eng.url.replace(/^https?:\/\//, "")}/api/v2</b>
              <span>State</span><b className="mono">stateless · runs kept in this browser</b></>
            ) : (
              <><span>Stored runs</span><b className="mono">{h?.runs ?? "…"}</b></>
            )}
            <span>GPU</span><b className="mono">none</b>
          </div>
          <div className="divider" />
          <div className="card-title" style={{ marginBottom: 10 }}><Gauge /> Speed</div>
          <div className="small muted">The recorded synthetic benchmark measured 0.9 s per generated cabinet image on 4 CPU cores using in-process Tesseract. Real photographs may require tiled or rotated OCR and can take longer. Each inspection reports its actual timings; no external AI inference API is needed.</div>
          <div className="divider" />
          <div className="card-title" style={{ marginBottom: 10 }}><Boxes /> Tools declared</div>
          <div className="row wrap" style={{ ["--gap" as string]: "6px" }}>
            {TOOLS.map((t) => <span key={t} className="tag">{t}</span>)}
            <span className="tag accent">AI coding assistant (declared)</span>
          </div>
        </Reveal>
      </div>

      {sample.data && (
        <Reveal className="engine-log-row">
          <div className="engine-log-copy">
            <div className="card-title"><Terminal /> A real run, as the engine logged it</div>
            <p className="small muted">{sample.data.meta.label} · cabinet <span className="mono">{sample.data.meta.cabinet}</span>. Parse, register, one narrow check per item, consensus, report: every line is a stage of the recorded inspection, with its own timing.</p>
            <a className="btn btn-sm" href={`#/run/${sample.data.meta.id}`}>Open this inspection</a>
          </div>
          <EngineLog lines={runLog(sample.data)} title={`ENGINE LOG · RUN ${sample.data.meta.id.slice(-4).toUpperCase()}`} />
        </Reveal>
      )}

      <div className="engine-grid">
        <Reveal className="card pad">
          <div className="card-title" style={{ marginBottom: 14 }}><FileCode2 /> Code map</div>
          <div className="filemap">
            {FILES.map(([f, d]) => (
              <div key={f}><span className="mono">{f}</span><span className="small muted">{d}</span></div>
            ))}
          </div>
        </Reveal>
        <Reveal className="card pad" delay={0.06}>
          <div className="card-head">
            <div className="card-title"><Network /> REST API</div>
            <a className="btn btn-sm" href={STATIC ? REPO_URL + "/eagle_eye#rest-api" : "/docs"} target="_blank" rel="noreferrer"><ExternalLink /> {STATIC ? "API reference" : "OpenAPI docs"}</a>
          </div>
          <div className="api-list">
            {API.map(([m, p, d]) => (
              <div key={p}>
                <span className={`api-m ${m.toLowerCase()}`}>{m}</span>
                <span className="mono small">{p}</span>
                <span className="tiny faint">{d}</span>
              </div>
            ))}
          </div>
          <div className="divider" />
          <div className="row tiny faint" style={{ ["--gap" as string]: "6px" }}><Cpu size={13} /> Same engine powers the CLI demo (<span className="mono">python demo.py</span>), the Streamlit app and this console.</div>
        </Reveal>
      </div>
    </div>
  );
}
