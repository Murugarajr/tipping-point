import type { Craft } from "./content";

export function Arrow({ diagonal = false }: { diagonal?: boolean }) {
  return <svg className="arrow-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" aria-hidden="true"><path d={diagonal ? "M6 18 18 6M6 6h12v12" : "M4 12h15m-6-6 6 6-6 6"} /></svg>;
}

export function Mark() {
  return <svg className="brand-mark" viewBox="0 0 40 40" aria-hidden="true"><rect x="1" y="1" width="38" height="38" rx="12" fill="currentColor" /><path d="M9 24h22" stroke="white" strokeWidth="2" /><circle cx="20" cy="15" r="5" fill="white" /><circle cx="29" cy="31" r="3" fill="#ff3b25" /></svg>;
}

export function CraftArt({ craft, className = "" }: { craft: Craft; className?: string }) {
  return <svg className={`craft-art ${className}`} viewBox="0 0 600 500" fill="none" aria-hidden="true">
    {craft === "clay" ? <>
      <rect width="600" height="500" fill="#e6e9e6" />
      <path d="M0 395c190-34 389-34 600 0v105H0Z" fill="#d3d6d0" />
      <ellipse cx="306" cy="414" rx="179" ry="24" fill="#b8bfb5" />
      <path d="M186 206c-6 36-47 91-40 143 8 61 49 70 155 70s148-16 155-75c5-50-43-107-48-138Z" fill="#bc6242" />
      <ellipse cx="297" cy="208" rx="111" ry="38" fill="#d88865" />
      <ellipse cx="297" cy="207" rx="86" ry="24" fill="#793c2e" />
      <path d="M179 297c59 19 164 20 239-1M168 320c72 21 178 20 261-2M168 345c72 22 178 21 263-2M180 370c67 18 151 17 235-1" stroke="#dd9573" strokeWidth="5" strokeLinecap="round" />
      <path d="m0 79 111 39 121 83c20 16 14 41-6 40l-54-32 29 49c13 22-9 39-24 21l-53-64-43-27L0 170" fill="#d8ab83" />
      <path d="m600 63-106 64-80 75c-22 19-11 40 8 34l37-26-19 58c-8 23 16 34 29 13l34-61 36-29 61-22" fill="#e2bb98" />
      <path d="m92 141 84 59m348-54-57 60" stroke="#bb865e" strokeWidth="3" strokeLinecap="round" />
      <path d="m478 375 34 19m-13-33 27 11" stroke="#9aa69a" strokeWidth="4" strokeLinecap="round" />
      <circle cx="75" cy="348" r="7" fill="#bc6242" /><circle cx="91" cy="360" r="4" fill="#bc6242" />
    </> : craft === "thread" ? <>
      <rect width="600" height="500" fill="#e8e8f0" />
      <path d="m-20 420 640-290M-20 440l640-290M-20 460l640-290M-20 480l640-290M-20 500l640-290" stroke="#d7d7e4" strokeWidth="2" />
      <circle cx="306" cy="261" r="175" fill="#bd8b53" /><circle cx="306" cy="261" r="162" fill="#f8f5e8" stroke="#e3bf8b" strokeWidth="8" />
      <path d="m294 78 2-37h27l2 38" stroke="#a7a6a2" strokeWidth="12" />
      <path d="M252 368c6-80 55-146 89-210M274 303c-48-9-61-42-62-69 43 9 66 28 62 69ZM305 242c41 3 65-17 76-44-39-4-63 12-76 44Z" stroke="#22734e" strokeWidth="7" strokeLinecap="round" strokeDasharray="3 8" />
      <path d="M325 163c-47-3-61-44-41-51 17-6 36 7 41 23 0-28 24-47 39-32 15 14-1 40-20 48 29-10 57 5 48 25-9 19-39 12-50-1-1 25-22 41-35 26-12-13 1-30 18-38Z" fill="#ff432d" />
      <path d="M419 378c48 7 65 45 102 34s20-56 58-57" stroke="#2357d9" strokeWidth="4" strokeLinecap="round" />
      <path d="m384 341 62 50" stroke="#717a87" strokeWidth="4" /><ellipse cx="390" cy="346" rx="3" ry="8" transform="rotate(-51 390 346)" stroke="#717a87" strokeWidth="2" />
    </> : <>
      <rect width="600" height="500" fill="#f0dfc9" />
      <path d="m79 405 289 48 169-125-281-62Z" fill="#c2a98b" />
      <path d="m101 147 258 51 148-102-251-44Z" fill="#265ce0" />
      <path d="m101 147 258 51v222l-258-51Z" fill="#fbf8ef" />
      <path d="m359 198 148-102v221L359 420Z" fill="#e6dfce" />
      <path d="m112 353 235 48m-235-60 235 48m-235-60 235 48m-235-60 235 48m-235-60 235 48" stroke="#d8d1c1" strokeWidth="2" />
      <path d="m101 147 26 6v220l-26-4Z" fill="#1644b6" />
      <path d="m170 179 3 24m1 26 3 24m1 26 3 24m1 26 3 24" stroke="#ff432d" strokeWidth="6" strokeLinecap="round" />
      <path d="m400 382 85 31 65-29-88-28Z" fill="#ff432d" />
      <path d="m40 87 33-16m-8 40 17-13" stroke="#bc9c73" strokeWidth="4" strokeLinecap="round" />
    </>}
  </svg>;
}

export function ThresholdArt() {
  return <svg className="threshold-art" viewBox="0 0 440 310" fill="none" aria-hidden="true">
    <path d="M28 224h384" stroke="white" strokeWidth="2" strokeDasharray="4 8" opacity=".65" />
    {[64, 142, 220, 298, 376].map((x, index) => <g key={x} transform={`translate(${x} ${index < 3 ? 120 : 167})`} opacity={index < 3 ? 1 : .45}>
      <circle cy="-28" r="17" stroke="white" strokeWidth="3" />
      <path d="M-28 47V16c0-16 12-24 28-24s28 8 28 24v31M-17 47V24m34 23V24" stroke="white" strokeWidth="3" strokeLinecap="round" />
    </g>)}
    <path d="m215 64 5-19 5 19 19 5-19 5-5 19-5-19-19-5Z" fill="white" />
    <path d="M52 263h204m-12-10 12 10-12 10" stroke="white" strokeWidth="2" strokeLinecap="round" />
    <text x="275" y="269" fill="white" fontSize="18" fontFamily="Arial, sans-serif">the decision</text>
  </svg>;
}
