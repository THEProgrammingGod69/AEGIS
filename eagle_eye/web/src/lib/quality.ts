/**
 * Capture assistant: a quick, in-browser quality check of a cabinet photo before it is inspected.
 * Sharpness = variance of the Laplacian on a 900 px copy (calibrated on the sample photos: sharp ≈ 400–1100,
 * a 3 px blur ≈ 80). Nothing here changes the verdict; it tells the technician to re-shoot before wasting a run.
 */
export type Level = "good" | "warn" | "bad";

export interface QualityCheck {
  key: string;
  label: string;
  level: Level;
  value: string;
  tip: string;
}

export interface PhotoQuality {
  width: number;
  height: number;
  score: number;
  level: Level;
  checks: QualityCheck[];
}

async function bitmap(src: Blob | string): Promise<ImageBitmap | HTMLImageElement> {
  if (typeof src !== "string") return createImageBitmap(src, { imageOrientation: "from-image" } as ImageBitmapOptions);
  const img = new Image();
  img.crossOrigin = "anonymous";
  img.src = src;
  await img.decode();
  return img;
}

export async function analyzePhoto(src: Blob | string): Promise<PhotoQuality> {
  const bmp = await bitmap(src);
  const W = "naturalWidth" in bmp ? bmp.naturalWidth : bmp.width;
  const H = "naturalHeight" in bmp ? bmp.naturalHeight : bmp.height;
  const k = Math.min(1, 900 / Math.max(W, H));
  const w = Math.max(8, Math.round(W * k));
  const h = Math.max(8, Math.round(H * k));
  const c = document.createElement("canvas");
  c.width = w;
  c.height = h;
  const g = c.getContext("2d", { willReadFrequently: true })!;
  g.drawImage(bmp, 0, 0, w, h);
  if ("close" in bmp) bmp.close();
  const px = g.getImageData(0, 0, w, h).data;
  const gray = new Float32Array(w * h);
  let sum = 0, sum2 = 0, clip = 0, dark = 0;
  for (let i = 0, j = 0; i < px.length; i += 4, j++) {
    const v = 0.299 * px[i] + 0.587 * px[i + 1] + 0.114 * px[i + 2];
    gray[j] = v;
    sum += v;
    sum2 += v * v;
    if (v > 250) clip++;
    if (v < 8) dark++;
  }
  const n = w * h;
  const mean = sum / n;
  const std = Math.sqrt(Math.max(0, sum2 / n - mean * mean));
  let ls = 0, ls2 = 0, ln = 0;
  for (let y = 1; y < h - 1; y++) {
    for (let x = 1; x < w - 1; x++) {
      const i = y * w + x;
      const l = gray[i - 1] + gray[i + 1] + gray[i - w] + gray[i + w] - 4 * gray[i];
      ls += l;
      ls2 += l * l;
      ln++;
    }
  }
  const lapVar = ls2 / ln - (ls / ln) ** 2;
  const bright = mean / 255;
  const glare = clip / n;
  const long = Math.max(W, H);

  const checks: QualityCheck[] = [
    {
      key: "res", label: "Resolution", value: `${W}×${H}`,
      level: long >= 2000 ? "good" : long >= 1200 ? "warn" : "bad",
      tip: long >= 2000 ? "Enough pixels to read ferrule text." : "Ferrule text is small; shoot closer or use the full camera resolution.",
    },
    {
      key: "sharp", label: "Sharpness", value: lapVar.toFixed(0),
      level: lapVar >= 250 ? "good" : lapVar >= 90 ? "warn" : "bad",
      tip: lapVar >= 250 ? "Edges are crisp." : "Looks blurred: hold still, tap to focus on the labels, then re-shoot.",
    },
    {
      key: "light", label: "Exposure", value: `${Math.round(bright * 100)}%`,
      level: bright >= 0.25 && bright <= 0.8 ? "good" : bright >= 0.15 && bright <= 0.9 ? "warn" : "bad",
      tip: bright < 0.25 ? "Too dark: switch on the cabinet light." : bright > 0.8 ? "Over-exposed: labels may wash out." : "Well exposed.",
    },
    {
      key: "glare", label: "Glare", value: `${(glare * 100).toFixed(1)}%`,
      level: glare <= 0.03 ? "good" : glare <= 0.08 ? "warn" : "bad",
      tip: glare <= 0.03 ? "No large reflections." : "Reflections on labels: change the angle or turn off the flash.",
    },
    {
      key: "contrast", label: "Contrast", value: (std / 255).toFixed(2),
      level: std / 255 >= 0.12 ? "good" : std / 255 >= 0.07 ? "warn" : "bad",
      tip: std / 255 >= 0.12 ? "Good separation between parts and backplate." : "Flat image: avoid haze and back-light.",
    },
  ];
  if (dark / n > 0.25) checks[2] = { ...checks[2], level: "warn", tip: "Large dark areas: make sure the whole backplate is lit." };
  const pts = { good: 1, warn: 0.55, bad: 0 };
  const score = Math.round((checks.reduce((a, c) => a + pts[c.level], 0) / checks.length) * 100);
  const level: Level = checks.some((c) => c.level === "bad") ? "bad" : checks.some((c) => c.level === "warn") ? "warn" : "good";
  return { width: W, height: H, score, level, checks };
}
