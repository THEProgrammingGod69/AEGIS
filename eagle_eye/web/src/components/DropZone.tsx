import { MorphSVGPlugin } from "gsap/MorphSVGPlugin";
import { Upload, X } from "lucide-react";
import { useEffect, useRef, useState, type ReactNode } from "react";
import { calm, gsap, useGSAP } from "../lib/gsap";

gsap.registerPlugin(MorphSVGPlugin);

interface Props {
  accept: string;
  file: File | null;
  onFile: (f: File | null) => void;
  title: string;
  hint?: ReactNode;
  icon?: ReactNode;
  compact?: boolean;
  preview?: boolean;
  children?: ReactNode;
}

const FILE = "M7 2.8h7.2l4.8 4.8v13.6H7z M14.2 2.8v4.8h4.8";
const CHECK = "M5.2 12.6l4.4 4.4 9.2-10";

/** Drag-and-drop file input. `preview` shows an image thumbnail for photos.
 *  #28: when a file lands, the border traces itself in (DrawSVG), the file name scrambles into place and the file
 *  icon morphs into a check (MorphSVG). */
export function DropZone({ accept, file, onFile, title, hint, icon, compact, preview, children }: Props) {
  const input = useRef<HTMLInputElement>(null);
  const root = useRef<HTMLDivElement>(null);
  const [over, setOver] = useState(false);
  const [thumb, setThumb] = useState<string | null>(null);
  const named = useRef<string | null>(null);

  useEffect(() => {
    if (!preview || !file) return setThumb(null);
    const u = URL.createObjectURL(file);
    setThumb(u);
    return () => URL.revokeObjectURL(u);
  }, [file, preview]);

  useGSAP(() => {
    const name = file?.name ?? null;
    const fresh = name && name !== named.current;
    named.current = name;
    if (!fresh || calm()) return;
    const el = root.current!;
    const tl = gsap.timeline();
    tl.fromTo(el.querySelector(".dz-border rect"), { drawSVG: "0%" }, { drawSVG: "100%", duration: 0.6, ease: "power2.inOut" });
    const title = el.querySelector<HTMLElement>(".drop-title");
    if (title) tl.from(title, { duration: 0.6, scrambleText: { text: name!.replace(/./g, "·"), chars: "CBPSX0123456789_-.", speed: 0.7 } }, "<");
    const icon = el.querySelector(".dz-icon");
    if (icon) tl.fromTo(icon, { morphSVG: FILE }, { morphSVG: CHECK, duration: 0.45, ease: "back.out(1.6)" }, "-=0.2");
  }, { scope: root, dependencies: [file?.name] });

  const pick = (f?: File) => {
    if (!f) return;
    const ok = accept.split(",").some((a) => f.name.toLowerCase().endsWith(a.trim().replace("*", "")) || f.type === a.trim());
    if (ok) onFile(f);
  };

  return (
    <div
      ref={root}
      className={`drop${compact ? " compact" : ""}${over ? " over" : ""}${file ? " has" : ""}`}
      onDragOver={(e) => { e.preventDefault(); setOver(true); }}
      onDragLeave={() => setOver(false)}
      onDrop={(e) => { e.preventDefault(); setOver(false); pick(e.dataTransfer.files?.[0]); }}
      onClick={() => input.current?.click()}
      role="button"
      tabIndex={0}
      data-spotlight=""
      onKeyDown={(e) => (e.key === "Enter" || e.key === " ") && input.current?.click()}
    >
      <svg className="dz-border" aria-hidden="true"><rect x="0.75" y="0.75" rx={compact ? 11 : 14} /></svg>
      <input ref={input} type="file" accept={accept} hidden onChange={(e) => { pick(e.target.files?.[0]); e.target.value = ""; }} />
      {thumb ? <img className="drop-thumb" src={thumb} alt="" /> : (
        <div className="drop-icon">
          {file ? (
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
              <path className="dz-icon" d={CHECK} />
            </svg>
          ) : icon ?? <Upload />}
        </div>
      )}
      <div className="drop-text">
        {/* keyed: ScrambleText rewrites this text node, so a new file gets a fresh element */}
        <div key={file?.name ?? ""} className="drop-title">{file ? file.name : title}</div>
        <div className="drop-hint">{file ? `${(file.size / 1024 / 1024).toFixed(2)} MB · click to replace` : hint}</div>
        {children}
      </div>
      {file && (
        <button className="btn btn-sm btn-icon btn-ghost drop-clear" onClick={(e) => { e.stopPropagation(); onFile(null); }} aria-label="Remove file">
          <X />
        </button>
      )}
    </div>
  );
}
