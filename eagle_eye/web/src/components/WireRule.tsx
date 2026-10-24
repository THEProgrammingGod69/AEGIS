/** Where a run's wire-colour rule came from (eagle_eye/wire_rules.py): the cabinet's own drawing legend, a wire list, a
 *  profile chosen for the project, or nothing but the universal green-and-yellow rule. Colour codes are not universal,
 *  so the console always says which rule judged the wires, and lists the standards a project can choose from. */
import { Cable } from "lucide-react";
import PROFILES from "../../../wire_profiles.json";
import { COLOUR_HEX, COLOUR_NAME, WIRE_CLASS_NAME } from "../lib/format";
import type { WireClass, WireRule } from "../lib/types";

interface Profile { name: string; region: string; edition: string; classes: Partial<Record<WireClass, string[]>>; verify: string }
const LIST = Object.entries((PROFILES as unknown as { profiles: Record<string, Profile> }).profiles);
const ORDER: WireClass[] = ["AC", "DC", "ALARM", "PE"];

export function WireCode({ c }: { c: string }) {
  return (
    <span className="wire-code" title={COLOUR_NAME[c] ?? c}>
      <i style={{ background: COLOUR_HEX[c] ?? "#333" }} />
      {c}
    </span>
  );
}

function sourceLine(r: WireRule) {
  if (r.kind === "legend") return <>From this drawing set&apos;s own wire-colour legend <span className="faint">{r.source?.replace("drawing legend", "").trim()}</span></>;
  if (r.kind === "profile") return <>Project profile: <b>{r.source?.replace("profile: ", "")}</b> <span className="faint">(the drawing set has no colour legend)</span></>;
  if (r.kind === "wire_list") return <>From the wire list: every terminal&apos;s wire has its own colour</>;
  return <>No colour legend in the drawing set and no project profile: only <b>green-and-yellow = protective earth</b> is checked</>;
}

export function WireRuleCard({ rule }: { rule: WireRule }) {
  const classes = ORDER.filter((k) => rule.classes[k]?.length);
  const circ = rule.circuits;
  const classed = circ ? Object.values(circ.classified).reduce((a, n) => a + (n ?? 0), 0) : 0;
  return (
    <div className="card pad wire-rule">
      <div className="card-head">
        <div>
          <div className="card-title"><Cable /> Wire colour rule</div>
          <div className="card-sub">{sourceLine(rule)}</div>
        </div>
      </div>
      {classes.length > 0 && (
        <div className="wire-rows">
          {classes.map((k) => (
            <div key={k} className="wire-row">
              <span className="tiny faint">{WIRE_CLASS_NAME[k]}</span>
              <span className="row wrap" style={{ ["--gap" as string]: "5px" }}>{rule.classes[k]!.map((c) => <WireCode key={c} c={c} />)}</span>
            </div>
          ))}
        </div>
      )}
      {rule.kind !== "wire_list" && (
        <div className="tiny faint wire-tally">
          {rule.ferrules != null && <span><b className="mono">{rule.judged ?? 0}</b> of {rule.ferrules} ferrule wires judged{rule.not_measured ? ` · ${rule.not_measured} not measurable in this photo` : ""}{rule.no_rule ? ` · ${rule.no_rule} outside the rule` : ""}</span>}
          {circ && <span>Circuit class of each wire from the drawing&apos;s own wiring: {classed} pins classed{circ.conflicts ? `, ${circ.conflicts} circuits left open (conflicting)` : ""}, never from the wire&apos;s colour</span>}
        </div>
      )}
      {rule.notes.filter(Boolean).map((n) => <div key={n} className="tiny faint">{n}</div>)}
      <details className="wire-standards">
        <summary className="tiny">Why colours are not assumed · standards a project can choose</summary>
        <p className="tiny faint">The same colour means different things: black is a phase under IEC 60445 but the neutral in India&apos;s legacy scheme, and white is the neutral under NFPA 79. The engine uses the cabinet&apos;s own legend first, a profile only when one is chosen for the project, and checks green-and-yellow for earth under every rule.</p>
        <table className="wire-table">
          <thead><tr><th>Profile</th>{ORDER.map((k) => <th key={k}>{k === "ALARM" ? "Alarm" : k}</th>)}</tr></thead>
          <tbody>
            {LIST.map(([id, p]) => (
              <tr key={id} className={rule.profile === id ? "on" : undefined} title={`${p.edition}. ${p.verify}`}>
                <td><div className="small">{p.name}</div><div className="tiny faint">{p.region}</div></td>
                {ORDER.map((k) => <td key={k}><span className="row wrap" style={{ ["--gap" as string]: "3px" }}>{(p.classes[k] ?? []).map((c) => <WireCode key={c} c={c} />)}{!(p.classes[k] ?? []).length && <span className="faint tiny">not set</span>}</span></td>)}
              </tr>
            ))}
          </tbody>
        </table>
      </details>
    </div>
  );
}
