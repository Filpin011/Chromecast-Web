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
import type { MediaTrack } from "@/lib/api/types";

function trackLabel(t: MediaTrack): string {
  return t.name || (t.language ? t.language.toUpperCase() : `Traccia ${t.id}`);
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
  const text = tracks.filter((t) => t.type === "TEXT");
  const audio = tracks.filter((t) => t.type === "AUDIO");
  if (!text.length && audio.length < 2) return null;
  const subsOn = text.some((t) => activeIds.includes(t.id));
  return (
    <DropdownMenu>
      <DropdownMenuTrigger render={<Button variant="ghost" size="icon" aria-label="Sottotitoli e audio" />}>
        <Captions className={subsOn ? "size-5 text-primary" : "size-5"} />
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="w-60">
        {text.length > 0 && (
          <DropdownMenuGroup>
            <DropdownMenuLabel>Sottotitoli</DropdownMenuLabel>
            <DropdownMenuItem onClick={() => onChange(nextActiveTracks(tracks, activeIds, "TEXT", null))}>
              <span className="flex-1">Disattivati</span>
              {!subsOn && <Check className="size-4" />}
            </DropdownMenuItem>
            {text.map((t) => (
              <DropdownMenuItem key={t.id} onClick={() => onChange(nextActiveTracks(tracks, activeIds, "TEXT", t.id))}>
                <span className="flex-1 truncate">{trackLabel(t)}</span>
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
                <AudioLines className="size-3.5" /> Audio
              </DropdownMenuLabel>
              {audio.map((t) => (
                <DropdownMenuItem key={t.id} onClick={() => onChange(nextActiveTracks(tracks, activeIds, "AUDIO", t.id))}>
                  <span className="flex-1 truncate">{trackLabel(t)}</span>
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
