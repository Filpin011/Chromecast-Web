"use client";

import { useState } from "react";
import { Slider } from "@/components/ui/slider";
import { formatTime } from "@/lib/format";

/** VOD seek bar: follows playback, lets the user scrub and commits on release. */
export function SeekBar({
  position,
  duration,
  disabled,
  onSeek,
}: {
  position: number;
  duration: number;
  disabled?: boolean;
  onSeek: (seconds: number) => void;
}) {
  const [scrub, setScrub] = useState<number | null>(null);
  const value = scrub ?? Math.min(position, duration);
  return (
    <div className="space-y-1">
      <Slider
        aria-label="Posizione"
        getAriaValueText={(_, v) => `${formatTime(v)} di ${formatTime(duration)}`}
        min={0}
        max={Math.max(1, duration)}
        step={1}
        value={value}
        disabled={disabled}
        onValueChange={(v) => setScrub(Array.isArray(v) ? v[0] : v)}
        onValueCommitted={(v) => {
          setScrub(null);
          onSeek(Array.isArray(v) ? v[0] : v);
        }}
      />
      <div className="flex justify-between font-mono text-xs text-muted-foreground tabular-nums">
        <span>{formatTime(value)}</span>
        <span>-{formatTime(Math.max(0, duration - value))}</span>
      </div>
    </div>
  );
}
