"use client";

import { AudioLines, Captions, Check } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuGroup,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { useT, type Translator } from "@/i18n";
import type { MediaTrack } from "@/lib/api/types";

function trackLabel(track: MediaTrack, tr: Translator): string {
  return track.name || (track.language ? track.language.toUpperCase() : tr("tracks.track", { id: track.id }));
}

/** Compute the new active ids when picking `track` (null = subtitles off). One per type. */
export function nextActiveTracks(
  tracks: MediaTrack[],
  active: number[],
  type: MediaTrack["type"],
  trackId: number | null,
): number[] {
  const ofType = new Set(tracks.filter((t) => t.type === type).map((t) => t.id));
  const kept = active.filter((id) => !ofType.has(id));
  return trackId == null ? kept : [...kept, trackId];
}

export function TrackPicker({
  tracks,
  activeIds,
  onChange,
}: {
  tracks: MediaTrack[];
  activeIds: number[];
  onChange: (ids: number[]) => void;
}) {
  const tr = useT();
  const text = tracks.filter((t) => t.type === "TEXT");
  const audio = tracks.filter((t) => t.type === "AUDIO");
  if (!text.length && audio.length < 2) return null;
  const subsOn = text.some((t) => activeIds.includes(t.id));
  return (
    <DropdownMenu>
      <DropdownMenuTrigger render={<Button variant="ghost" size="icon" aria-label={tr("tracks.label")} />}>
        <Captions className={subsOn ? "size-5 text-primary" : "size-5"} />
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="w-60">
        {text.length > 0 && (
          <DropdownMenuGroup>
            <DropdownMenuLabel>{tr("tracks.subtitles")}</DropdownMenuLabel>
            <DropdownMenuItem onClick={() => onChange(nextActiveTracks(tracks, activeIds, "TEXT", null))}>
              <span className="flex-1">{tr("tracks.off")}</span>
              {!subsOn && <Check className="size-4" />}
            </DropdownMenuItem>
            {text.map((t) => (
              <DropdownMenuItem key={t.id} onClick={() => onChange(nextActiveTracks(tracks, activeIds, "TEXT", t.id))}>
                <span className="flex-1 truncate">{trackLabel(t, tr)}</span>
                {activeIds.includes(t.id) && <Check className="size-4" />}
              </DropdownMenuItem>
            ))}
          </DropdownMenuGroup>
        )}
        {audio.length > 1 && (
          <>
            {text.length > 0 && <DropdownMenuSeparator />}
            <DropdownMenuGroup>
              <DropdownMenuLabel className="flex items-center gap-1.5">
                <AudioLines className="size-3.5" /> {tr("tracks.audio")}
              </DropdownMenuLabel>
              {audio.map((t) => (
                <DropdownMenuItem key={t.id} onClick={() => onChange(nextActiveTracks(tracks, activeIds, "AUDIO", t.id))}>
                  <span className="flex-1 truncate">{trackLabel(t, tr)}</span>
                  {activeIds.includes(t.id) && <Check className="size-4" />}
                </DropdownMenuItem>
              ))}
            </DropdownMenuGroup>
          </>
        )}
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
