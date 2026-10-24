import { AnimatePresence, motion } from "framer-motion";
import { CornerDownLeft, Search } from "lucide-react";
import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";

export interface Command {
  id: string;
  group: string;
  label: string;
  hint?: string;
  icon?: ReactNode;
  keywords?: string;
  run: () => void;
}

/** Ctrl/⌘ K: jump anywhere, start any demo step, switch engine mode. */
export function CommandPalette({ open, onClose, commands }: { open: boolean; onClose: () => void; commands: Command[] }) {
  const [q, setQ] = useState("");
  const [i, setI] = useState(0);
  const input = useRef<HTMLInputElement>(null);
  const list = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (open) {
      setQ("");
      setI(0);
      setTimeout(() => input.current?.focus(), 30);
    }
  }, [open]);

  const shown = useMemo(() => {
    const words = q.toLowerCase().split(/\s+/).filter(Boolean);
    return commands.filter((c) => {
      const hay = `${c.group} ${c.label} ${c.hint ?? ""} ${c.keywords ?? ""}`.toLowerCase();
      return words.every((w) => hay.includes(w));
    });
  }, [q, commands]);

  useEffect(() => setI(0), [q]);
  useEffect(() => {
    list.current?.querySelector<HTMLElement>(`[data-i="${i}"]`)?.scrollIntoView({ block: "nearest" });
  }, [i]);

  const exec = (c?: Command) => {
    if (!c) return;
    onClose();
    setTimeout(c.run, 10);
  };

  const onKey = (e: React.KeyboardEvent) => {
    if (e.key === "ArrowDown") { e.preventDefault(); setI((x) => Math.min(shown.length - 1, x + 1)); }
    else if (e.key === "ArrowUp") { e.preventDefault(); setI((x) => Math.max(0, x - 1)); }
    else if (e.key === "Enter") { e.preventDefault(); exec(shown[i]); }
    else if (e.key === "Escape") { e.preventDefault(); onClose(); }
  };

  let lastGroup = "";
  return (
    <AnimatePresence>
      {open && (
        <motion.div className="modal-back palette-back" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} onMouseDown={onClose}>
          <motion.div className="palette card" role="dialog" aria-label="Command palette" initial={{ opacity: 0, y: -12, scale: 0.98 }} animate={{ opacity: 1, y: 0, scale: 1 }} exit={{ opacity: 0, y: -8 }} transition={{ duration: 0.16 }} onMouseDown={(e) => e.stopPropagation()}>
            <div className="palette-input">
              <Search />
              <input ref={input} autoFocus value={q} onChange={(e) => setQ(e.target.value)} onKeyDown={onKey} placeholder="Jump to a page, run a demo step, open the latest inspection…" aria-label="Search commands" />
              <kbd>Esc</kbd>
            </div>
            <div className="palette-list" ref={list}>
              {shown.length === 0 && <div className="empty small muted">No matching command.</div>}
              {shown.map((c, n) => {
                const head = c.group !== lastGroup ? (lastGroup = c.group) : null;
                return (
                  <div key={c.id}>
                    {head && <div className="palette-group">{head}</div>}
                    <button data-i={n} className={`palette-item${n === i ? " on" : ""}`} onMouseEnter={() => setI(n)} onClick={() => exec(c)}>
                      <span className="palette-icon">{c.icon}</span>
                      <span className="grow">{c.label}</span>
                      {c.hint && <span className="tiny faint">{c.hint}</span>}
                      {n === i && <CornerDownLeft size={14} className="faint" />}
                    </button>
                  </div>
                );
              })}
            </div>
          </motion.div>
        </motion.div>
      )}
    </AnimatePresence>
  );
}
