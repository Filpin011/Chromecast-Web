"use client";

import { ChevronDown, Radio } from "lucide-react";
import type { ReactNode } from "react";
import { Button } from "@/components/ui/button";
import { useT } from "@/i18n";
import { cn } from "@/lib/utils";

/**
 * Top bar of a player sheet (TV Now Playing, built-in player): close chevron, "Playing on <target>"
 * centred, and the sheet's own controls (track / quality menus) on the right.
 */
export function PlayerSheetHeader({ target, onClose, children }: { target: string; onClose?: () => void; children?: ReactNode }) {
  const t = useT();
  return (
    <div className="flex items-center gap-1 px-2 pt-2">
      {onClose && (
        <Button variant="ghost" size="icon" aria-label={t("common.close")} onClick={onClose}>
          <ChevronDown className="size-6" />
        </Button>
      )}
      <div className="min-w-0 flex-1 text-center">
        <p className="text-[0.7rem] font-medium tracking-wider text-muted-foreground uppercase">{t("player.playingOn")}</p>
        <p className="truncate text-sm font-semibold">{target}</p>
      </div>
      {children}
    </div>
  );
}

/** A live stream's position line: the time (or delay behind live) and "Go live". */
export function LiveEdgeRow({
  time,
  onGoLive,
  disabled,
  overVideo = false,
}: {
  time: string;
  onGoLive: () => void;
  disabled?: boolean;
  /** Drawn over the video (full screen): light text instead of muted. */
  overVideo?: boolean;
}) {
  const t = useT();
  return (
    <div className="flex items-center justify-between gap-2">
      <span className={cn("font-mono text-xs tabular-nums", overVideo ? "text-white/70" : "text-muted-foreground")}>{time}</span>
      <Button variant="secondary" size="sm" onClick={onGoLive} disabled={disabled} className="gap-1.5">
        <Radio className="size-4 text-live" />
        {t("player.goLive")}
      </Button>
    </div>
  );
}
