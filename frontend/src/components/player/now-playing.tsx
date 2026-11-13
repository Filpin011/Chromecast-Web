"use client";

import {
  ChevronDown,
  ImageIcon,
  ListOrdered,
  MonitorPlay,
  Radio,
  Redo2,
  RotateCcw,
  RotateCw,
  SkipBack,
  SkipForward,
  Square,
  Undo2,
} from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { isActivePlayback } from "@/hooks/use-app-state";
import { useCommand } from "@/hooks/use-command";
import { useNow } from "@/hooks/use-now";
import { api } from "@/lib/api";
import type { Device, PlayerState } from "@/lib/api/types";
import { formatTime } from "@/lib/format";
import { useT } from "@/i18n";
import { haptic } from "@/lib/haptics";
import { tvMedia } from "@/lib/local-player/sources";
import { extrapolatePosition, isLive } from "@/lib/player";
import { errorMessage } from "@/lib/query";
import { cn } from "@/lib/utils";
import { useAppStore } from "@/stores/app-store";
import { openLocalPlayer } from "@/stores/local-player-store";
import { Artwork } from "./artwork";
import { LiveBadge } from "./live-badge";
import { PlayPauseButton } from "./play-pause-button";
import { QueueList } from "./queue-list";
import { SeekBar } from "./seek-bar";
import { TrackPicker } from "./track-picker";
import { VolumeControl } from "./volume-control";

/** Shown only when the transport row is at least 384px wide (2×44 + 4×48 + 72+8 + 6×4 gap = 384). */
const NARROW_HIDDEN = "hidden @min-[384px]/transport:inline-flex";

export function SkipButton({
  seconds,
  onClick,
  disabled,
  className,
}: {
  seconds: number;
  onClick: () => void;
  disabled?: boolean;
  className?: string;
}) {
  const t = useT();
  const back = seconds < 0;
  const big = Math.abs(seconds) >= 30;
  const Icon = back ? (big ? Undo2 : RotateCcw) : big ? Redo2 : RotateCw;
  return (
    <Button
      variant="ghost"
      size="icon-lg"
      disabled={disabled}
      aria-label={t.plural(back ? "player.skipBack" : "player.skipForward", Math.abs(seconds))}
      onClick={onClick}
      className={cn("relative rounded-full", className)}
    >
      <Icon className="size-6" />
      <span className="absolute bottom-0.5 text-[0.6rem] font-bold tabular-nums">{Math.abs(seconds)}</span>
    </Button>
  );
}

export interface NowPlayingContentProps {
  device: Device;
  player: PlayerState;
  receivedAt: number;
  onClose?: () => void;
}

/** Full "Now Playing" UI. Pure presentational + commands; wrapped by the sheet. */
export function NowPlayingContent({ device, player, receivedAt, onClose }: NowPlayingContentProps) {
  const t = useT();
  const { run } = useCommand(device.id);
  const [tab, setTab] = useState<"player" | "queue">("player");
  const live = isLive(player);
  // The idle image is reported as PLAYING by the receiver: it is not user playback.
  const active = isActivePlayback(player);
  const idleImage = player.showing_idle_image && !active;
  const now = useNow(500, active && player.player_state === "PLAYING");
  const position = extrapolatePosition(player, receivedAt, now);
  const canSeek = active && player.seekable;

  const setTracks = async (ids: number[]) => {
    haptic();
    try {
      useAppStore.getState().applyPlayer(await api.player.setTracks(device.id, ids));
    } catch (e) {
      toast.error(errorMessage(e, t("player.trackFailed")));
    }
  };

  const watchHere = () => {
    const media = tvMedia(device.id, player, position);
    if (!media) return;
    void run("pause"); // paused, not stopped: "Send to TV" resumes it from where this device got to
    onClose?.();
    openLocalPlayer(media);
  };

  const showIdle = async () => {
    haptic();
    try {
      useAppStore.getState().applyPlayer(await api.player.showIdle(device.id));
      toast.success(t("player.idleShown"));
    } catch (e) {
      toast.error(errorMessage(e));
    }
  };

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="flex items-center gap-1 px-2 pt-2">
        {onClose && (
          <Button variant="ghost" size="icon" aria-label={t("common.close")} onClick={onClose}>
            <ChevronDown className="size-6" />
          </Button>
        )}
        <div className="min-w-0 flex-1 text-center">
          <p className="text-[0.7rem] font-medium tracking-wider text-muted-foreground uppercase">{t("player.playingOn")}</p>
          <p className="truncate text-sm font-semibold">{device.name}</p>
        </div>
        <TrackPicker tracks={player.tracks} activeIds={player.active_track_ids} onChange={setTracks} />
        {!player.tracks.length && <span className="size-11" />}
      </div>

      <div className="mx-auto mt-2 grid w-full max-w-xs grid-cols-2 gap-1 rounded-xl bg-muted p-1 text-sm">
        {(["player", "queue"] as const).map((id) => (
          <button
            key={id}
            type="button"
            onClick={() => setTab(id)}
            aria-pressed={tab === id}
            className={cn(
              "flex h-9 items-center justify-center gap-1.5 rounded-lg font-medium transition-all",
              tab === id ? "bg-background shadow-sm" : "text-muted-foreground",
            )}
          >
            {id === "player" ? t("player.tabPlayer") : <><ListOrdered className="size-4" /> {t("common.queue")} {player.queue.length > 0 && `(${player.queue.length})`}</>}
          </button>
        ))}
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto overscroll-contain px-5 pt-5 pb-[max(env(safe-area-inset-bottom),1.25rem)]">
        {tab === "queue" ? (
          <QueueList deviceId={device.id} queue={player.queue} />
        ) : (
          <div className="mx-auto flex max-w-md flex-col gap-6">
            <Artwork
              player={player}
              eq={false}
              className={cn(
                "aspect-video w-full overflow-hidden rounded-2xl shadow-2xl shadow-black/40 transition-transform duration-500",
                player.player_state === "PAUSED" && "scale-95",
              )}
            />

            <div className="space-y-1">
              <div className="flex items-start gap-2">
                <h2 className="line-clamp-2 flex-1 text-xl font-bold tracking-tight">
                  {idleImage ? t("settings.idleImage") : active ? (player.title ?? t("player.untitled")) : t("player.nothingPlaying")}
                </h2>
                {active && live && <LiveBadge className="mt-1" />}
              </div>
              <p className="text-sm text-muted-foreground">
                {active ? (player.player_state === "BUFFERING" ? t("player.loading") : player.app_name ?? "Default Media Receiver") : idleImage ? t("player.shownOnTv") : t("player.idle")}
              </p>
            </div>

            {active && !live && player.duration ? (
              <SeekBar position={position} duration={player.duration} disabled={!canSeek} onSeek={(s) => run("seek", s)} />
            ) : active && live ? (
              <div className="flex items-center justify-between gap-2">
                <span className="font-mono text-xs text-muted-foreground tabular-nums">{formatTime(position)}</span>
                <Button variant="secondary" size="sm" onClick={() => run("go_live")} className="gap-1.5">
                  <Radio className="size-4 text-live" />
                  {t("player.goLive")}
                </Button>
              </div>
            ) : null}

            {/* Seven controls need 384px: the ±10 s pair only shows when the row (a container) is
                that wide, so Previous / Next never get pushed off a 360px phone. */}
            <div
              data-testid="transport-row"
              className="@container/transport flex items-center justify-center gap-1"
            >
              {player.queue.length > 0 || active ? (
                <Button
                  variant="ghost"
                  size="icon"
                  aria-label={t("player.previous")}
                  title={t("player.previousHint")}
                  onClick={() => run("previous")}
                  disabled={!active}
                >
                  <SkipBack className="size-5" fill="currentColor" />
                </Button>
              ) : null}
              <SkipButton seconds={live ? -10 : -30} onClick={() => run("seek_relative", live ? -10 : -30)} disabled={!canSeek} />
              {!live && <SkipButton seconds={-10} onClick={() => run("seek_relative", -10)} disabled={!canSeek} className={NARROW_HIDDEN} />}
              <PlayPauseButton
                size="lg"
                state={active ? player.player_state : "PAUSED"}
                onToggle={() => run(active ? "toggle" : "play")}
                disabled={idleImage}
                className="mx-1"
              />
              {!live && <SkipButton seconds={10} onClick={() => run("seek_relative", 10)} disabled={!canSeek} className={NARROW_HIDDEN} />}
              <SkipButton seconds={live ? 10 : 30} onClick={() => run("seek_relative", live ? 10 : 30)} disabled={!canSeek} />
              {player.queue.length > 0 || active ? (
                <Button variant="ghost" size="icon" aria-label={t("player.next")} onClick={() => run("next")} disabled={!player.queue.length}>
                  <SkipForward className="size-5" fill="currentColor" />
                </Button>
              ) : null}
            </div>

            <VolumeControl level={player.volume_level} muted={player.muted} onCommand={run} />

            <div className="grid grid-cols-2 gap-2">
              <Button
                variant="secondary"
                size="lg"
                onClick={watchHere}
                disabled={!active || !player.original_input}
                className="col-span-2 gap-2"
              >
                <MonitorPlay className="size-4" />
                {t("localPlayer.watchOnThisDevice")}
              </Button>
              <Button variant="secondary" size="lg" onClick={() => run("stop")} disabled={!active} className="gap-2">
                <Square className="size-4" fill="currentColor" />
                {t("player.stop")}
              </Button>
              <Button
                variant="secondary"
                size="lg"
                onClick={showIdle}
                className={cn("gap-2", player.showing_idle_image && "text-primary")}
              >
                <ImageIcon className="size-4" />
                {t("player.idleImageShort")}
              </Button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
