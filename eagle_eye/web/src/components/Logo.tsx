/** EAGLE EYE mark: an eye whose iris is a registration crosshair (drawing-anchored vision). */
export function EyeMark({ size = 30, animated = false }: { size?: number; animated?: boolean }) {
  return (
    <svg width={size} height={size} viewBox="0 0 48 48" fill="none" aria-hidden="true">
      <defs>
        <linearGradient id="ee-g" x1="4" y1="8" x2="44" y2="40" gradientUnits="userSpaceOnUse">
          <stop stopColor="#bae6fd" />
          <stop offset="0.5" stopColor="#38bdf8" />
          <stop offset="1" stopColor="#818cf8" />
        </linearGradient>
        <radialGradient id="ee-i" cx="24" cy="24" r="9" gradientUnits="userSpaceOnUse">
          <stop stopColor="#fde68a" />
          <stop offset="0.55" stopColor="#f5b544" />
          <stop offset="1" stopColor="#b45309" />
        </radialGradient>
      </defs>
      <rect x="1.5" y="1.5" width="45" height="45" rx="13" fill="#0a111c" stroke="url(#ee-g)" strokeOpacity="0.55" />
      <path d="M6 24c4.6-7.6 10.6-11.4 18-11.4S37.4 16.4 42 24c-4.6 7.6-10.6 11.4-18 11.4S10.6 31.6 6 24Z" stroke="url(#ee-g)" strokeWidth="2.2" strokeLinejoin="round" />
      <circle cx="24" cy="24" r="7.6" fill="url(#ee-i)" />
      <circle cx="24" cy="24" r="3" fill="#05070b" />
      <g stroke="#e0f2fe" strokeWidth="1.1" strokeLinecap="round" opacity="0.9">
        <path d="M24 13.5v4M24 30.5v4M13.5 24h4M30.5 24h4" />
      </g>
      {animated && (
        <circle cx="24" cy="24" r="11" stroke="#38bdf8" strokeWidth="1" strokeDasharray="3 4" opacity="0.7">
          <animateTransform attributeName="transform" type="rotate" from="0 24 24" to="360 24 24" dur="9s" repeatCount="indefinite" />
        </circle>
      )}
      <circle cx="26.4" cy="21.6" r="1.3" fill="#fff" opacity="0.9" />
    </svg>
  );
}

export function Brand() {
  return (
    <a className="brand" href="#/" aria-label="EAGLE EYE home">
      <EyeMark size={34} animated />
      <div>
        <div className="brand-name">EAGLE EYE</div>
        <div className="brand-sub">Cabinet QC · Team ENIGMA</div>
      </div>
    </a>
  );
}
