import type { LucideIcon } from "lucide-react";
import { cn } from "@/lib/utils";

/**
 * A rounded square holding one icon: the leading visual of a playlist card, the M3U result card and
 * every empty state. `primary` = brand-tinted (an object you can open), `muted` = neutral (an empty state).
 */
export function IconTile({
  icon: Icon,
  tone = "primary",
  size = "md",
  className,
  iconClassName,
}: {
  icon: LucideIcon;
  tone?: "primary" | "muted";
  /** md = 48px (list cards), lg = 64px (empty states). */
  size?: "md" | "lg";
  className?: string;
  iconClassName?: string;
}) {
  return (
    <div
      className={cn(
        "grid shrink-0 place-items-center",
        size === "lg" ? "size-16 rounded-2xl" : "size-12 rounded-xl",
        tone === "primary" ? "bg-primary/12 text-primary" : "bg-muted text-muted-foreground",
        className,
      )}
    >
      <Icon className={cn(size === "lg" ? "size-7" : "size-6", iconClassName)} />
    </div>
  );
}
