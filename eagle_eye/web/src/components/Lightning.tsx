/** WebGL lightning (after React Bits' "Lightning" background): an fbm-displaced bolt with a soft glow, blended over
 *  the dark CTA band with `screen`. Built to stay cheap: rendered at half resolution with DPR capped, paused when
 *  the band is off-screen or the tab is hidden, a single static frame in Calm, and nothing at all without WebGL. */
import { useEffect, useRef } from "react";
import { calm } from "../lib/gsap";

const VERT = `attribute vec2 p; void main(){ gl_Position = vec4(p, 0.0, 1.0); }`;

const FRAG = `
precision mediump float;
uniform vec2 uRes;
uniform float uTime;
uniform float uHue;
uniform float uX;
uniform float uSpeed;
uniform float uIntensity;
uniform float uSize;

float hash11(float p){ p = fract(p * .1031); p *= p + 33.33; p *= p + p; return fract(p); }
float hash12(vec2 p){ vec3 p3 = fract(vec3(p.xyx) * .1031); p3 += dot(p3, p3.yzx + 33.33); return fract((p3.x + p3.y) * p3.z); }
mat2 rot(float t){ float c = cos(t), s = sin(t); return mat2(c, -s, s, c); }
float noise(vec2 p){
  vec2 i = floor(p), f = fract(p);
  float a = hash12(i), b = hash12(i + vec2(1., 0.)), c = hash12(i + vec2(0., 1.)), d = hash12(i + vec2(1., 1.));
  vec2 t = f * f * (3. - 2. * f);
  return mix(mix(a, b, t.x), mix(c, d, t.x), t.y);
}
float fbm(vec2 p){
  float v = 0., a = .5;
  for (int i = 0; i < 6; i++) { v += a * noise(p); p *= rot(.45); p *= 2.; a *= .5; }
  return v;
}
vec3 hsv2rgb(vec3 c){
  vec3 rgb = clamp(abs(mod(c.x * 6. + vec3(0., 4., 2.), 6.) - 3.) - 1., 0., 1.);
  return c.z * mix(vec3(1.), rgb, c.y);
}
void main(){
  vec2 uv = gl_FragCoord.xy / uRes;
  uv = 2. * uv - 1.;
  uv.x *= uRes.x / uRes.y;
  uv.x += uX;
  float t = uTime * uSpeed;
  uv += 2. * fbm(uv * uSize + .8 * t) - 1.;
  float d = abs(uv.x);
  // a slow pulse instead of a strobe: professional, never a flash
  float flick = mix(.05, .075, noise(vec2(t * 2.3, 0.)));
  vec3 base = hsv2rgb(vec3(uHue / 360., .62, .9));
  vec3 col = base * (flick / max(d, .002)) * uIntensity;
  // a fainter twin bolt for depth
  vec2 uv2 = uv + vec2(.55, 0.) + .35 * (fbm(uv * uSize * 1.7 - .6 * t) - .5);
  col += hsv2rgb(vec3((uHue + 45.) / 360., .55, .8)) * (.018 / max(abs(uv2.x), .002)) * uIntensity;
  gl_FragColor = vec4(col, 1.);
}`;

export function Lightning({ hue = 205, xOffset = -0.6, speed = 0.6, intensity = 0.7, size = 1.6, className }: {
  hue?: number; xOffset?: number; speed?: number; intensity?: number; size?: number; className?: string;
}) {
  const ref = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    const cv = ref.current!;
    const gl = cv.getContext("webgl", { antialias: false, alpha: false, premultipliedAlpha: false, powerPreference: "low-power" });
    if (!gl) {
      cv.style.display = "none";
      return;
    }
    const sh = (type: number, src: string) => {
      const s = gl.createShader(type)!;
      gl.shaderSource(s, src);
      gl.compileShader(s);
      return s;
    };
    const prog = gl.createProgram()!;
    gl.attachShader(prog, sh(gl.VERTEX_SHADER, VERT));
    gl.attachShader(prog, sh(gl.FRAGMENT_SHADER, FRAG));
    gl.linkProgram(prog);
    if (!gl.getProgramParameter(prog, gl.LINK_STATUS)) {
      cv.style.display = "none";
      return;
    }
    gl.useProgram(prog);
    const buf = gl.createBuffer();
    gl.bindBuffer(gl.ARRAY_BUFFER, buf);
    gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([-1, -1, 1, -1, -1, 1, -1, 1, 1, -1, 1, 1]), gl.STATIC_DRAW);
    const loc = gl.getAttribLocation(prog, "p");
    gl.enableVertexAttribArray(loc);
    gl.vertexAttribPointer(loc, 2, gl.FLOAT, false, 0, 0);
    const u = (n: string) => gl.getUniformLocation(prog, n);
    const uRes = u("uRes"), uTime = u("uTime");
    gl.uniform1f(u("uHue"), hue);
    gl.uniform1f(u("uX"), xOffset);
    gl.uniform1f(u("uSpeed"), speed);
    gl.uniform1f(u("uIntensity"), intensity);
    gl.uniform1f(u("uSize"), size);

    const SCALE = 0.5 * Math.min(1.5, window.devicePixelRatio || 1); // half resolution, DPR capped
    const resize = () => {
      const w = Math.max(1, Math.round(cv.clientWidth * SCALE));
      const h = Math.max(1, Math.round(cv.clientHeight * SCALE));
      if (cv.width !== w || cv.height !== h) {
        cv.width = w;
        cv.height = h;
        gl.viewport(0, 0, w, h);
      }
      gl.uniform2f(uRes, w, h);
    };
    resize();

    const t0 = performance.now();
    const frame = (now: number) => {
      gl.uniform1f(uTime, (now - t0) / 1000);
      gl.drawArrays(gl.TRIANGLES, 0, 6);
    };
    if (calm()) {
      frame(t0 + 4200); // one still frame
      const ro = new ResizeObserver(() => { resize(); frame(t0 + 4200); });
      ro.observe(cv);
      return () => ro.disconnect();
    }

    let raf = 0;
    let visible = false;
    const loop = (now: number) => {
      frame(now);
      raf = requestAnimationFrame(loop);
    };
    const sync = () => {
      const run = visible && !document.hidden;
      if (run && !raf) raf = requestAnimationFrame(loop);
      if (!run && raf) { cancelAnimationFrame(raf); raf = 0; }
    };
    const io = new IntersectionObserver(([e]) => { visible = e.isIntersecting; sync(); }, { rootMargin: "120px" });
    io.observe(cv);
    const ro = new ResizeObserver(resize);
    ro.observe(cv);
    document.addEventListener("visibilitychange", sync);
    return () => {
      cancelAnimationFrame(raf);
      io.disconnect();
      ro.disconnect();
      document.removeEventListener("visibilitychange", sync);
      gl.getExtension("WEBGL_lose_context")?.loseContext();
    };
  }, [hue, xOffset, speed, intensity, size]);

  return <canvas ref={ref} className={`lightning${className ? ` ${className}` : ""}`} aria-hidden="true" />;
}
