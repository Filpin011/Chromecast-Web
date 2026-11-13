"use client";

import { Cast, ChevronDown, Minimize, PictureInPicture2, Radio } from "lucide-react";
import { useCallback, useEffect, useRef, useState, type ReactNode } from "react";
import { Button } from "@/components/ui/button";
import { useT } from "@/i18n";
import { formatTime } from "@/lib/format";
import { cn } from "@/lib/utils";
import { LiveBadge } from "./live-badge";
import { SkipButton } from "./now-playing";
import { PlayPauseButton } from "./play-pause-button";
import { SeekBar } from "./seek-bar";
import { VolumeControl } from "./volume-control";

/** Readable on any frame, bright ones included. */
const CENTER_BUTTON = "bg-black/35 text-white backdrop-blur-sm hover:bg-black/50";

/** Controls hide after this long without input while playing. */
const HIDE_AFTER_MS = 3000;

export interface FullscreenControlsProps {
  title: string;
  subtitle?: string | null;
  live: boolean;
  vod: boolean;
  ready: boolean;
  paused: boolean;
  buffering: boolean;
  time: number;
  duration: number;
  /** Seconds behind the live edge (live streams). */
  behind: number;
  volume: number;
  muted: boolean;
  /** Quality / track menus, already wired to portal into the full-screen element. */
  menus: ReactNode;
  onToggle: () => void;
  onSeek: (s: number) => void;
  onSkip: (delta: number) => void;
  onGoLive: () => void;
  onVolume: (level: number) => void;
  onMuted: (muted: boolean) => void;
  onExit: () => void;
  onPip?: () => void;
  onCast?: () => void;
}

/**
 * The player's own controls while full screen (instead of the browser's native ones): same look as the
 * sheet, over the video, with gradients top and bottom. They fade out while playing and come back on any
 * pointer/keyboard activity; a tap on the video shows/hides them (touch) or plays/pauses (mouse).
 */
export function FullscreenControls(p: FullscreenControlsProps) {
  const t = useT();
  const [shown, setShown] = useState(true);
  const timer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);

  const poke = useCallback(() => {
    setShown(true);
    clearTimeout(timer.current);
    timer.current = setTimeout(() => setShown(false), HIDE_AFTER_MS);
  }, []);

  // the props change several times a second (time updates): keyboard handling reads the latest ones
  const latest = useRef(p);
  useEffect(() => {
    latest.current = p;
  });

  useEffect(() => {
    timer.current = setTimeout(() => setShown(false), HIDE_AFTER_MS); // shown on mount, start the countdown
    const onKey = (e: KeyboardEvent) => {
      poke();
      if (e.target instanceof HTMLInputElement) return;
      const c = latest.current;
      const k = e.key.toLowerCase();
      if (k === " " || k === "k") c.onToggle();
      else if (k === "arrowleft") c.onSkip(-10);
      else if (k === "arrowright") c.onSkip(10);
      else if (k === "m") c.onMuted(!c.muted);
      else if (k === "f") c.onExit();
      else return;
      e.preventDefault();
    };
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("keydown", onKey);
      clearTimeout(timer.current);
    };
  }, [poke]);

  // never hide while paused or still loading: there is nothing to look at but the controls
  const visible = shown || p.paused || !p.ready;
  const interactive = visible ? "pointer-events-auto" : "pointer-events-none";

  return (
    <div
      data-testid="fullscreen-controls"
      className={cn("dark absolute inset-0 text-white", !visible && "cursor-none")}
      onPointerMove={poke}
    >
      {/* tap layer under the controls */}
      <div
        className="absolute inset-0"
        onPointerUp={(e) => {
          if (e.pointerType === "mouse") {
            p.onToggle();
            poke();
          } else if (visible && p.ready && !p.paused) {
            clearTimeout(timer.current);
            setShown(false);
          } else poke();
        }}
        onDoubleClick={p.onExit}
      />

      <div
        className={cn(
          "pointer-events-none absolute inset-0 flex flex-col justify-between transition-opacity duration-300",
          visible ? "opacity-100" : "opacity-0",
        )}
      >
        <div
          className={cn(
            "flex items-start gap-2 bg-linear-to-b from-black/80 via-black/40 to-transparent pb-12",
            "pt-[max(env(safe-area-inset-top),0.75rem)] pr-[max(env(safe-area-inset-right),1rem)] pl-[max(env(safe-area-inset-left),0.5rem)]",
          )}
        >
          <Button variant="ghost" size="icon" aria-label={t("localPlayer.exitFullscreen")} onClick={p.onExit} className={interactive}>
            <ChevronDown className="size-6" />
          </Button>
          <div className="min-w-0 flex-1 pt-1">
            <h2 className="truncate text-base font-bold tracking-tight sm:text-lg">{p.title}</h2>
            {p.subtitle && <p className="truncate text-xs text-white/70 sm:text-sm">{p.subtitle}</p>}
          </div>
          {p.live && <LiveBadge className="mt-2.5" dim={p.behind > 10} />}
          <div className={cn("flex items-center", interactive)}>{p.menus}</div>
        </div>

        <div className="flex items-center justify-center gap-4 sm:gap-8">
          <SkipButton seconds={-10} onClick={() => p.onSkip(-10)} disabled={!p.ready} className={cn(CENTER_BUTTON, interactive)} />
          <PlayPauseButton
            size="lg"
            state={!p.ready || (p.buffering && !p.paused) ? "BUFFERING" : p.paused ? "PAUSED" : "PLAYING"}
            onToggle={() => {
              p.onToggle();
              poke();
            }}
            className={interactive}
          />
          <SkipButton
            seconds={10}
            onClick={() => p.onSkip(10)}
            disabled={!p.ready || (p.live && p.behind < 1)}
            className={cn(CENTER_BUTTON, interactive)}
          />
        </div>

        <div
          className={cn(
            "space-y-2 bg-linear-to-t from-black/85 via-black/50 to-transparent pt-12",
            "pr-[max(env(safe-area-inset-right),1rem)] pb-[max(env(safe-area-inset-bottom),0.75rem)] pl-[max(env(safe-area-inset-left),1rem)]",
          )}
        >
          <div className={interactive}>
            {p.vod ? (
              <SeekBar position={p.time} duration={p.duration} disabled={!p.ready} onSeek={p.onSeek} />
            ) : p.live ? (
              <div className="flex items-center justify-between gap-2">
                <span className="font-mono text-xs text-white/70 tabular-nums">
                  {p.behind > 5 ? `-${formatTime(p.behind)}` : formatTime(p.time)}
                </span>
                <Button variant="secondary" size="sm" onClick={p.onGoLive} disabled={!p.ready} className="gap-1.5">
                  <Radio className="size-4 text-live" />
                  {t("player.goLive")}
                </Button>
              </div>
            ) : null}
          </div>
          <div className={cn("flex items-center gap-1", interactive)}>
            <div className="w-40 sm:w-56">
              <VolumeControl
                level={p.volume}
                muted={p.muted}
                onCommand={(action, value) => {
                  if (action === "mute") p.onMuted(true);
                  else if (action === "unmute") p.onMuted(false);
                  else if (action === "volume" && value != null) p.onVolume(value);
                }}
              />
            </div>
            <span className="flex-1" />
            {p.onCast && (
              <Button variant="ghost" onClick={p.onCast} className="gap-2" aria-label={t("localPlayer.sendToTv")}>
                <Cast className="size-5" />
                <span className="hidden sm:inline">{t("localPlayer.sendToTv")}</span>
              </Button>
            )}
            {p.onPip && (
              <Button variant="ghost" size="icon" onClick={p.onPip} aria-label={t("localPlayer.pip")}>
                <PictureInPicture2 className="size-5" />
              </Button>
            )}
            <Button variant="ghost" size="icon" onClick={p.onExit} aria-label={t("localPlayer.exitFullscreen")}>
              <Minimize className="size-5" />
            </Button>
          </div>
        </div>
      </div>
    </div>
  );
}
