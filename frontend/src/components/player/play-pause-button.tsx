"use client";

import { Loader2, Pause, Play } from "lucide-react";
import { Button } from "@/components/ui/button";
import type { PlayerStateName } from "@/lib/api/types";
import { useT } from "@/i18n";
import { cn } from "@/lib/utils";

export function PlayPauseButton({
  state,
  onToggle,
  size = "md",
  className,
  disabled,
}: {
  state: PlayerStateName;
  onToggle: () => void;
  size?: "md" | "lg";
  className?: string;
  disabled?: boolean;
}) {
  const t = useT();
  const playing = state === "PLAYING";
  const buffering = state === "BUFFERING";
  const Icon = buffering ? Loader2 : playing ? Pause : Play;
  return (
    <Button
      size={size === "lg" ? "icon-lg" : "icon"}
      variant={size === "lg" ? "default" : "ghost"}
      aria-label={playing ? t("player.pause") : t("player.play")}
      disabled={disabled}
      onClick={(e) => {
        e.stopPropagation();
        onToggle();
      }}
      className={cn(size === "lg" && "size-18 rounded-full shadow-lg shadow-primary/30", className)}
    >
      <Icon
        className={cn(size === "lg" ? "size-8" : "size-6", buffering && "animate-spin", !playing && !buffering && "translate-x-px")}
        fill={buffering ? "none" : "currentColor"}
      />
    </Button>
  );
}
