import { useId } from "react";

/** EAGLE EYE mark: an aurora tile with a white eye whose iris is a registration crosshair (drawing-anchored vision). */
export function EyeMark({ size = 30, animated = false }: { size?: number; animated?: boolean }) {
  const id = useId().replace(/:/g, "");
  return (
    <svg className="eye-mark" width={size} height={size} viewBox="0 0 48 48" fill="none" aria-hidden="true">
      <defs>
        <linearGradient id={`${id}t`} x1="2" y1="4" x2="46" y2="44" gradientUnits="userSpaceOnUse">
          <stop stopColor="#004b8d" />
          <stop offset="0.45" stopColor="#0a66e8" />
          <stop offset="0.8" stopColor="#6c47d9" />
          <stop offset="1" stopColor="#00b8e0" />
        </linearGradient>
        <radialGradient id={`${id}i`} cx="24" cy="24" r="8" gradientUnits="userSpaceOnUse">
          <stop stopColor="#0a66e8" />
          <stop offset="0.62" stopColor="#1c74c9" />
          <stop offset="1" stopColor="#004b8d" />
        </radialGradient>
      </defs>
      <rect x="1.5" y="1.5" width="45" height="45" rx="13" fill={`url(#${id}t)`} />
      <rect x="2" y="2" width="44" height="44" rx="12.5" stroke="#fff" strokeOpacity="0.28" />
      <path className="eye-lid" d="M6.5 24c4.4-7.4 10.3-11.1 17.5-11.1S37.1 16.6 41.5 24c-4.4 7.4-10.3 11.1-17.5 11.1S10.9 31.4 6.5 24Z" fill="#fff" />
      <g className="iris">
        <circle cx="24" cy="24" r="7.8" fill={`url(#${id}i)`} />
        <circle cx="24" cy="24" r="5.2" stroke="#7fe7ff" strokeWidth="1.2" />
        <circle cx="24" cy="24" r="2.6" fill="#004b8d" />
        <circle cx="26.2" cy="21.8" r="1.2" fill="#fff" opacity="0.95" />
      </g>
      <g stroke="#7fe7ff" strokeWidth="1.3" strokeLinecap="round">
        <path d="M24 5.5v5M24 37.5v5M3.8 24h3M41.2 24h3" />
      </g>
      {animated && (
        <circle cx="24" cy="24" r="11" stroke="#fff" strokeWidth="0.9" strokeDasharray="2.5 4" opacity="0.55">
          <animateTransform attributeName="transform" type="rotate" from="0 24 24" to="360 24 24" dur="12s" repeatCount="indefinite" />
        </circle>
      )}
    </svg>
  );
}

export function Brand() {
  return (
    <a className="brand logo" href="#/" aria-label="EAGLE EYE home">
      <EyeMark size={36} animated />
      <div>
        <div className="brand-name">EAGLE EYE</div>
        <div className="brand-sub">Cabinet QC · Team ENIGMA</div>
      </div>
    </a>
  );
}
