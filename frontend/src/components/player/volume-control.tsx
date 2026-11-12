"use client";

import { Volume1, Volume2, VolumeX } from "lucide-react";
import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Slider } from "@/components/ui/slider";
import { formatNumber, useT } from "@/i18n";
import type { ControlAction } from "@/lib/api/types";

export function VolumeControl({
  level,
  muted,
  onCommand,
}: {
  level: number;
  muted: boolean;
  onCommand: (action: ControlAction, value?: number) => void;
}) {
  const t = useT();
  const [drag, setDrag] = useState<number | null>(null);
  const shown = drag ?? (muted ? 0 : level);
  const Icon = muted || shown === 0 ? VolumeX : shown < 0.5 ? Volume1 : Volume2;
  return (
    <div className="flex items-center gap-2">
      <Button
        variant="ghost"
        size="icon"
        aria-label={muted ? t("volume.unmute") : t("volume.mute")}
        aria-pressed={muted}
        onClick={() => onCommand(muted ? "unmute" : "mute")}
      >
        <Icon className="size-5" />
      </Button>
      <Slider
        aria-label={t("volume.label")}
        getAriaValueText={(_, v) => formatNumber(v / 100, { style: "percent" }, t.locale)}
        className="flex-1"
        min={0}
        max={100}
        step={1}
        value={Math.round(shown * 100)}
        onValueChange={(v) => setDrag((Array.isArray(v) ? v[0] : v) / 100)}
        onValueCommitted={(v) => {
          setDrag(null);
          onCommand("volume", (Array.isArray(v) ? v[0] : v) / 100);
        }}
      />
      <span className="w-9 text-right font-mono text-xs text-muted-foreground tabular-nums">
        {Math.round(shown * 100)}
      </span>
    </div>
  );
}
