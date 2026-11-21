"use client";

import { Pause, Play } from "lucide-react";
import { Spinner } from "@/components/ui/spinner";
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
  const Icon = playing ? Pause : Play;
  const iconSize = size === "lg" ? "size-8" : "size-6";
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
      {buffering ? (
        <Spinner className={iconSize} />
      ) : (
        <Icon className={cn(iconSize, !playing && "translate-x-px")} fill="currentColor" />
      )}
    </Button>
  );
}
