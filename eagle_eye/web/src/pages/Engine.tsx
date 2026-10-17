import { Boxes, Code2, Cpu, ExternalLink, FileCode2, Network, Puzzle, ServerCog, Wrench } from "lucide-react";
import { Reveal } from "../components/ui";
import { STATIC, api } from "../lib/api";
import { REPO_URL } from "../lib/static";
import { useAsync } from "../lib/hooks";

const FILES = [
  ["inspector.py", "The engine: drawing parser, registration, the 5 plug-in checks, consensus and root-cause skip. Read this first."],
  ["service.py", "Run store: artefacts per run, re-check chains, proof crops, Fault Forge scoring."],
  ["server.py", "FastAPI backend + this console. One inspection at a time on a background worker, live progress."],
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
];

const TOOLS = ["Python", "OpenCV", "PyMuPDF", "Tesseract OCR", "NumPy", "openpyxl", "ReportLab", "FastAPI", "React", "Streamlit"];

export function Engine() {
  const checks = useAsync(api.checks);
  const health = useAsync(api.health);
  const h = health.data;
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
          <Reveal key={c.name} className="card pad check-card" delay={i * 0.05}>
            <div className="row between">
              <span className="tag accent">@check("{c.name}")</span>
              <Puzzle size={16} className="faint" />
            </div>
            <h3>{c.title}</h3>
            <p className="check-q">“{c.question}”</p>
            <p className="tiny faint">{c.doc}</p>
          </Reveal>
        ))}
        <Reveal className="card pad check-card add" delay={0.25}>
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
          <div className="card-title" style={{ marginBottom: 14 }}><ServerCog /> {STATIC ? "Recorded on" : "This machine"}</div>
          <div className="kv">
            <span>Engine</span><b className="mono">EAGLE EYE {h?.version ?? "…"}</b>
            <span>OCR</span><b className="mono" style={{ color: h ? (h.tesseract.ok ? "var(--pass)" : "var(--fail)") : undefined }}>{h ? h.tesseract.version ?? h.tesseract.error : "…"}</b>
            <span>Binary</span><b className="mono ellipsis" title={h?.tesseract.cmd}>{h?.tesseract.cmd ?? "…"}</b>
            <span>OCR lanes</span><b className="mono">{h?.workers ?? "…"} parallel · {h?.cpu ?? "…"} CPU cores</b>
            <span>Stored runs</span><b className="mono">{h?.runs ?? "…"}</b>
            <span>Cloud / GPU</span><b className="mono">none</b>
          </div>
          <div className="divider" />
          <div className="card-title" style={{ marginBottom: 10 }}><Boxes /> Tools declared</div>
          <div className="row wrap" style={{ ["--gap" as string]: "6px" }}>
            {TOOLS.map((t) => <span key={t} className="tag">{t}</span>)}
            <span className="tag accent">AI coding assistant (declared)</span>
          </div>
        </Reveal>
      </div>

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
