import { FileCheck2, Upload, X } from "lucide-react";
import { useEffect, useRef, useState, type ReactNode } from "react";

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

/** Drag-and-drop file input. `preview` shows an image thumbnail for photos. */
export function DropZone({ accept, file, onFile, title, hint, icon, compact, preview, children }: Props) {
  const input = useRef<HTMLInputElement>(null);
  const [over, setOver] = useState(false);
  const [thumb, setThumb] = useState<string | null>(null);

  useEffect(() => {
    if (!preview || !file) return setThumb(null);
    const u = URL.createObjectURL(file);
    setThumb(u);
    return () => URL.revokeObjectURL(u);
  }, [file, preview]);

  const pick = (f?: File) => {
    if (!f) return;
    const ok = accept.split(",").some((a) => f.name.toLowerCase().endsWith(a.trim().replace("*", "")) || f.type === a.trim());
    if (ok) onFile(f);
  };

  return (
    <div
      className={`drop${compact ? " compact" : ""}${over ? " over" : ""}${file ? " has" : ""}`}
      onDragOver={(e) => { e.preventDefault(); setOver(true); }}
      onDragLeave={() => setOver(false)}
      onDrop={(e) => { e.preventDefault(); setOver(false); pick(e.dataTransfer.files?.[0]); }}
      onClick={() => input.current?.click()}
      role="button"
      tabIndex={0}
      onKeyDown={(e) => (e.key === "Enter" || e.key === " ") && input.current?.click()}
    >
      <input ref={input} type="file" accept={accept} hidden onChange={(e) => { pick(e.target.files?.[0]); e.target.value = ""; }} />
      {thumb ? <img className="drop-thumb" src={thumb} alt="" /> : <div className="drop-icon">{file ? <FileCheck2 /> : icon ?? <Upload />}</div>}
      <div className="drop-text">
        <div className="drop-title">{file ? file.name : title}</div>
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
