import type { LucideIcon } from "lucide-react";
import type { ReactNode } from "react";
import { cn } from "@/lib/utils";

export type SegmentSize = "sm" | "default" | "lg";

export interface SegmentOption<T extends string> {
  value: T;
  label: ReactNode;
  icon?: LucideIcon;
  /** Small trailing number (e.g. how many items a tab holds); hidden when 0 / undefined. */
  count?: number;
  /** `lang` of the label (a language's native name). */
  lang?: string;
  disabled?: boolean;
}

/**
 * The app's one segmented switch (iOS-style pill group on `bg-muted`), for every "pick one of a few"
 * control: library tabs, Player / Queue, theme, language, popup policy, browser mode, import source.
 *
 * - `kind="radio"` (default): a `radiogroup` of `radio`s, for settings and modes.
 * - `kind="tab"`: a `tablist` of `tab`s, for switching what is shown below.
 * - `compactIcons`: icons are hidden on narrow phones (< 420px) so label + count fit in a third of the width.
 */
export function SegmentedControl<T extends string>({
  options,
  value,
  onChange,
  kind = "radio",
  size = "default",
  compactIcons = false,
  disabled = false,
  className,
  ...aria
}: {
  options: readonly SegmentOption<T>[];
  /** `null` = nothing selected yet (e.g. the theme before hydration). */
  value: T | null;
  onChange: (value: T) => void;
  kind?: "radio" | "tab";
  /** `sm` = 36px, small text (narrow places: sidebar, menus); default 36px; `lg` = 40px (page-level tabs). */
  size?: SegmentSize;
  compactIcons?: boolean;
  disabled?: boolean;
  className?: string;
  "aria-label"?: string;
  "aria-labelledby"?: string;
}) {
  return (
    <div
      role={kind === "tab" ? "tablist" : "radiogroup"}
      {...aria}
      className={cn("grid gap-1 rounded-xl bg-muted p-1", className)}
      style={{ gridTemplateColumns: `repeat(${options.length}, minmax(0, 1fr))` }}
    >
      {options.map(({ value: v, label, icon: Icon, count, lang, disabled: optDisabled }) => {
        const active = value === v;
        return (
          <button
            key={v}
            type="button"
            role={kind}
            {...(kind === "tab" ? { "aria-selected": active } : { "aria-checked": active })}
            lang={lang}
            disabled={disabled || optDisabled}
            onClick={() => onChange(v)}
            className={cn(
              "flex min-w-0 items-center justify-center gap-1.5 rounded-lg px-1 font-medium transition-all disabled:opacity-50",
              size === "lg" ? "h-10 text-sm" : size === "sm" ? "h-9 text-xs" : "h-9 text-sm",
              active ? "bg-background text-foreground shadow-sm" : "text-muted-foreground hover:text-foreground",
            )}
          >
            {Icon && <Icon className={cn("size-4 shrink-0", compactIcons && "max-[420px]:hidden")} />}
            <span className="truncate">{label}</span>
            {count ? <span className="text-xs text-muted-foreground tabular-nums">{count}</span> : null}
          </button>
        );
      })}
    </div>
  );
}
