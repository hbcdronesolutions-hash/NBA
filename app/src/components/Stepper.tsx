import { Minus, Plus } from "lucide-react";
import type { ReactNode } from "react";

export function Stepper({
  value,
  onChange,
  min,
  max,
  step = 1,
  children,
}: {
  value: number;
  onChange: (v: number) => void;
  min: number;
  max: number;
  step?: number;
  children: ReactNode;
}) {
  return (
    <div className="stepper">
      <button aria-label="Moins" disabled={value - step < min} onClick={() => onChange(value - step)}>
        <Minus size={18} strokeWidth={2.4} />
      </button>
      <div className="stepper-val">{children}</div>
      <button aria-label="Plus" disabled={value + step > max} onClick={() => onChange(value + step)}>
        <Plus size={18} strokeWidth={2.4} />
      </button>
    </div>
  );
}
