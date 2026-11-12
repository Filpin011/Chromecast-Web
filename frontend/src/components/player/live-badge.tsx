"use client";

import { useT } from "@/i18n";
import { cn } from "@/lib/utils";

export function LiveBadge({ className, dim = false }: { className?: string; dim?: boolean }) {
  const t = useT();
  return (
    <span
      className={cn(
        "inline-flex h-5 items-center gap-1 rounded-full px-2 text-[0.65rem] font-bold tracking-wider uppercase",
        dim ? "bg-muted text-muted-foreground" : "bg-live text-white",
        className,
      )}
    >
      <span className={cn("size-1.5 rounded-full", dim ? "bg-muted-foreground" : "animate-pulse bg-white")} />
      {t("player.live")}
    </span>
  );
}
