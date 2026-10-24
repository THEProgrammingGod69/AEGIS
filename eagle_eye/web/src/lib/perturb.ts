/**
 * Robustness Lab: shop-floor camera problems applied to a photo in the browser (canvas), so the live engine can be
 * shown what a bad phone shot does to it. Same function for the preview (small) and the upload (full size).
 */
export interface Perturb {
  rotate: number;     // degrees, camera roll
  keystone: number;   // 0..0.3, top narrower than bottom (shot from below)
  bright: number;     // 0.5..1.5
  contrast: number;   // 0.5..1.5
  blur: number;       // px at full resolution
  noise: number;      // 0..40, sensor noise sigma (8-bit levels)
  warm: number;       // -1 (cool / blue LED) .. 1 (warm / sodium)
  glare: number;      // 0..1, a specular hot-spot
  quality: number;    // JPEG quality 0.3..0.95
}

export const NEUTRAL: Perturb = { rotate: 0, keystone: 0, bright: 1, contrast: 1, blur: 0, noise: 0, warm: 0, glare: 0, quality: 0.92 };

export const PRESETS: { key: string; label: string; p: Perturb }[] = [
  { key: "mild", label: "Mild", p: { ...NEUTRAL, rotate: 3, bright: 0.92, blur: 0.6, noise: 4, warm: 0.2, quality: 0.85 } },
  { key: "moderate", label: "Moderate", p: { ...NEUTRAL, rotate: 6, keystone: 0.06, bright: 0.8, contrast: 0.9, blur: 1.2, noise: 8, warm: 0.4, glare: 0.25, quality: 0.75 } },
  { key: "hard", label: "Hard", p: { ...NEUTRAL, rotate: -9, keystone: 0.1, bright: 0.68, contrast: 0.82, blur: 2, noise: 14, warm: -0.5, glare: 0.45, quality: 0.6 } },
  { key: "extreme", label: "Extreme", p: { ...NEUTRAL, rotate: 13, keystone: 0.16, bright: 0.55, contrast: 0.7, blur: 3.4, noise: 24, warm: 0.8, glare: 0.7, quality: 0.45 } },
];

export function describe(p: Perturb): string {
  const parts: string[] = [];
  if (p.rotate) parts.push(`tilt ${p.rotate > 0 ? "+" : ""}${p.rotate}°`);
  if (p.keystone) parts.push(`keystone ${Math.round(p.keystone * 100)}%`);
  if (p.bright !== 1) parts.push(`light ${Math.round(p.bright * 100)}%`);
  if (p.contrast !== 1) parts.push(`contrast ${Math.round(p.contrast * 100)}%`);
  if (p.blur) parts.push(`blur ${p.blur}px`);
  if (p.noise) parts.push(`noise σ${p.noise}`);
  if (p.warm) parts.push(p.warm > 0 ? `warm cast ${Math.round(p.warm * 100)}%` : `cool cast ${Math.round(-p.warm * 100)}%`);
  if (p.glare) parts.push(`glare ${Math.round(p.glare * 100)}%`);
  if (p.quality < 0.9) parts.push(`JPEG q${Math.round(p.quality * 100)}`);
  return parts.join(" · ") || "untouched";
}

export async function loadImage(src: string): Promise<HTMLImageElement> {
  const img = new Image();
  img.crossOrigin = "anonymous";
  img.src = src;
  await img.decode();
  return img;
}

/** Render `img` through the perturbation into a canvas `maxSide` px on its long side (0 = full size). */
export function render(img: HTMLImageElement, p: Perturb, maxSide = 0): HTMLCanvasElement {
  const k = maxSide ? Math.min(1, maxSide / Math.max(img.naturalWidth, img.naturalHeight)) : 1;
  const w = Math.round(img.naturalWidth * k);
  const h = Math.round(img.naturalHeight * k);

  // 1. keystone: draw in horizontal strips, narrower towards the top
  const ks = document.createElement("canvas");
  ks.width = w;
  ks.height = h;
  const kg = ks.getContext("2d")!;
  kg.fillStyle = "#1c1f24";
  kg.fillRect(0, 0, w, h);
  const strips = Math.min(120, h);
  for (let i = 0; i < strips; i++) {
    const y0 = (i / strips) * h;
    const sh = h / strips + 1;
    const scale = 1 - p.keystone * (1 - i / strips);
    const sw = w * scale;
    kg.drawImage(img, 0, (y0 / h) * img.naturalHeight, img.naturalWidth, (sh / h) * img.naturalHeight, (w - sw) / 2, y0, sw, sh);
  }

  // 2. roll: rotate on a canvas big enough to keep every corner
  const a = (p.rotate * Math.PI) / 180;
  const W = Math.round(Math.abs(w * Math.cos(a)) + Math.abs(h * Math.sin(a)));
  const H = Math.round(Math.abs(w * Math.sin(a)) + Math.abs(h * Math.cos(a)));
  const c = document.createElement("canvas");
  c.width = W;
  c.height = H;
  const g = c.getContext("2d", { willReadFrequently: true })!;
  g.fillStyle = "#1c1f24";
  g.fillRect(0, 0, W, H);
  const blurPx = p.blur * k;
  const filters = `brightness(${p.bright}) contrast(${p.contrast})${blurPx > 0.05 ? ` blur(${blurPx.toFixed(2)}px)` : ""}`;
  const canFilter = "filter" in g;
  if (canFilter) g.filter = filters;
  g.translate(W / 2, H / 2);
  g.rotate(a);
  g.drawImage(ks, -w / 2, -h / 2);
  g.setTransform(1, 0, 0, 1, 0, 0);
  if (canFilter) g.filter = "none";

  // 3. colour cast
  if (p.warm) {
    g.globalCompositeOperation = "soft-light";
    g.fillStyle = p.warm > 0 ? `rgba(255,150,40,${Math.abs(p.warm) * 0.55})` : `rgba(60,140,255,${Math.abs(p.warm) * 0.55})`;
    g.fillRect(0, 0, W, H);
  }
  // 4. glare hot-spot (upper right, like a ceiling light reflected in the door glass)
  if (p.glare) {
    g.globalCompositeOperation = "screen";
    const r = Math.max(W, H) * (0.18 + 0.14 * p.glare);
    const grd = g.createRadialGradient(W * 0.68, H * 0.3, 0, W * 0.68, H * 0.3, r);
    grd.addColorStop(0, `rgba(255,255,250,${0.35 + 0.6 * p.glare})`);
    grd.addColorStop(0.45, `rgba(255,255,250,${0.12 + 0.25 * p.glare})`);
    grd.addColorStop(1, "rgba(255,255,250,0)");
    g.fillStyle = grd;
    g.fillRect(0, 0, W, H);
  }
  g.globalCompositeOperation = "source-over";

  // 5. sensor noise (fast pseudo-gaussian: sum of uniforms)
  if (p.noise) {
    const im = g.getImageData(0, 0, W, H);
    const d = im.data;
    let s = 1234567;
    const rnd = () => ((s = (s * 1103515245 + 12345) & 0x7fffffff) / 0x7fffffff);
    const sig = p.noise * 1.7;
    for (let i = 0; i < d.length; i += 4) {
      const n = (rnd() + rnd() + rnd() - 1.5) * sig;
      d[i] += n;
      d[i + 1] += n;
      d[i + 2] += n;
    }
    g.putImageData(im, 0, 0);
  }
  return c;
}

export function toFile(c: HTMLCanvasElement, p: Perturb, name: string): Promise<File> {
  return new Promise((resolve, reject) =>
    c.toBlob((b) => (b ? resolve(new File([b], name, { type: "image/jpeg" })) : reject(new Error("Could not encode the photo"))), "image/jpeg", p.quality),
  );
}
