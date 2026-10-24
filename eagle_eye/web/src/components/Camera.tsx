import { AnimatePresence, motion } from "framer-motion";
import { Camera as CameraIcon, RefreshCw, X } from "lucide-react";
import { useEffect, useRef, useState } from "react";

/**
 * Shop-floor capture: live camera with a framing guide for the backplate. Falls back to the phone's own camera
 * app (file input with capture=environment) when the browser cannot open a stream.
 */
export function CameraCapture({ open, onClose, onPhoto }: { open: boolean; onClose: () => void; onPhoto: (f: File) => void }) {
  const video = useRef<HTMLVideoElement>(null);
  const fallback = useRef<HTMLInputElement>(null);
  const [err, setErr] = useState<string | null>(null);
  const [facing, setFacing] = useState<"environment" | "user">("environment");
  const [flash, setFlash] = useState(false);

  useEffect(() => {
    if (!open) return;
    let stream: MediaStream | null = null;
    let cancelled = false;
    setErr(null);
    if (!navigator.mediaDevices?.getUserMedia) {
      setErr("This browser cannot open the camera here. Use your phone's camera instead.");
      return;
    }
    navigator.mediaDevices
      .getUserMedia({ video: { facingMode: facing, width: { ideal: 3840 }, height: { ideal: 2160 } }, audio: false })
      .then((s) => {
        if (cancelled) return s.getTracks().forEach((t) => t.stop());
        stream = s;
        if (video.current) {
          video.current.srcObject = s;
          void video.current.play();
        }
      })
      .catch((e: Error) => setErr(e.name === "NotAllowedError" ? "Camera permission was denied." : `Camera unavailable (${e.message}).`));
    return () => {
      cancelled = true;
      stream?.getTracks().forEach((t) => t.stop());
    };
  }, [open, facing]);

  const shoot = () => {
    const v = video.current;
    if (!v || !v.videoWidth) return;
    const c = document.createElement("canvas");
    c.width = v.videoWidth;
    c.height = v.videoHeight;
    c.getContext("2d")!.drawImage(v, 0, 0);
    setFlash(true);
    setTimeout(() => setFlash(false), 220);
    c.toBlob((b) => {
      if (!b) return;
      const stamp = new Date().toISOString().slice(0, 19).replace(/[:T]/g, "-");
      onPhoto(new File([b], `camera_${stamp}.jpg`, { type: "image/jpeg" }));
      onClose();
    }, "image/jpeg", 0.95);
  };

  return (
    <AnimatePresence>
      {open && (
        <motion.div className="modal-back" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} onClick={onClose}>
          <motion.div className="card camera" initial={{ scale: 0.97, y: 10 }} animate={{ scale: 1, y: 0 }} exit={{ scale: 0.98 }} onClick={(e) => e.stopPropagation()}>
            <div className="row between camera-head">
              <div>
                <div className="card-title"><CameraIcon /> Capture the cabinet</div>
                <div className="card-sub">Fit the whole backplate inside the guide, square-on, labels in focus.</div>
              </div>
              <button className="btn btn-icon btn-ghost" onClick={onClose} aria-label="Close camera"><X /></button>
            </div>
            <div className="camera-view">
              {err ? (
                <div className="empty">
                  <CameraIcon />
                  <div className="small muted">{err}</div>
                  <button className="btn btn-primary" onClick={() => fallback.current?.click()}>Open phone camera</button>
                </div>
              ) : (
                <>
                  <video ref={video} playsInline muted />
                  <div className="camera-guide"><i /><i /><i /><i /><span>Backplate</span></div>
                  {flash && <div className="camera-flash" />}
                </>
              )}
            </div>
            <div className="row between">
              <button className="btn btn-sm btn-ghost" onClick={() => setFacing(facing === "environment" ? "user" : "environment")}><RefreshCw /> Switch camera</button>
              <button className="btn btn-primary btn-lg camera-shutter" onClick={shoot} disabled={!!err}><CameraIcon /> Capture</button>
            </div>
            <input ref={fallback} type="file" accept="image/*" capture="environment" hidden
              onChange={(e) => { const f = e.target.files?.[0]; if (f) { onPhoto(f); onClose(); } e.target.value = ""; }} />
          </motion.div>
        </motion.div>
      )}
    </AnimatePresence>
  );
}
