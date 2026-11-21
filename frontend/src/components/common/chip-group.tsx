import type { ReactNode } from "react";
import { cn } from "@/lib/utils";

export interface ChipOption<T> {
  value: T;
  label: ReactNode;
}

/**
 * A horizontally scrolling row of pill chips, one selected (playlist group filter, detected-stream
 * picker). `kind="radio"` filters a list, `kind="tab"` switches what is shown below. The row bleeds to
 * the screen edges: pass the page gutter as `className` (e.g. `-mx-4 px-4`).
 */
export function ChipGroup<T extends string | null>({
  options,
  value,
  onChange,
  kind = "radio",
  className,
  "aria-label": ariaLabel,
}: {
  options: readonly ChipOption<T>[];
  value: T;
  onChange: (value: T) => void;
  kind?: "radio" | "tab";
  className?: string;
  "aria-label": string;
}) {
  return (
    <div
      role={kind === "tab" ? "tablist" : "radiogroup"}
      aria-label={ariaLabel}
      className={cn("flex gap-2 overflow-x-auto no-scrollbar", className)}
    >
      {options.map(({ value: v, label }) => {
        const active = v === value;
        return (
          <button
            key={v ?? "__none"}
            type="button"
            role={kind}
            {...(kind === "tab" ? { "aria-selected": active } : { "aria-checked": active })}
            onClick={() => onChange(v)}
            className={cn(
              "h-9 shrink-0 rounded-full border px-3.5 text-xs font-medium whitespace-nowrap transition-colors",
              active ? "border-primary bg-primary text-primary-foreground" : "bg-card text-muted-foreground",
            )}
          >
            {label}
          </button>
        );
      })}
    </div>
  );
}
