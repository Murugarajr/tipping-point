import { useEffect, useRef, useState } from "react";
import { minorToPounds, poundsToMinor } from "./model";

export function MoneyField({ label, value, onChange }: { label: string; value: number; onChange: (value: number) => void }) {
  const [raw, setRaw] = useState(minorToPounds(value));
  const previous = useRef(value);
  useEffect(() => {
    if (previous.current !== value) { setRaw(minorToPounds(value)); previous.current = value; }
  }, [value]);
  return <label>{label} <span className="field-unit">GBP</span><input type="text" inputMode="decimal" required pattern="[0-9]+([.][0-9]{1,2})?" title="Enter pounds with up to two decimal places." value={raw}
    onChange={(event) => {
      setRaw(event.target.value);
      const parsed = poundsToMinor(event.target.value);
      if (parsed !== null) { previous.current = parsed; onChange(parsed); }
      event.target.setCustomValidity(parsed === null ? "Enter a valid GBP amount with up to two decimal places." : "");
    }}
    onBlur={() => { const parsed = poundsToMinor(raw); if (parsed !== null) setRaw(minorToPounds(parsed)); }} /></label>;
}
export function NumberField({ label, value, onChange, min = 0 }: { label: string; value: number; onChange: (value: number) => void; min?: number }) {
  return <label>{label}<input type="number" required min={min} step="1" value={value} onChange={(event) => onChange(Number(event.target.value))} /></label>;
}
