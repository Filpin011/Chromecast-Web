"use client";

import { AlertTriangle, Cast, Check, ChevronDown, Loader2, Maximize, PictureInPicture2, Radio, RotateCw, Settings2 } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { Drawer, DrawerContent, DrawerTitle } from "@/components/ui/drawer";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuGroup,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { useLocalVideo } from "@/hooks/use-local-video";
import { useIsDesktop } from "@/hooks/use-media-query";
import { useT } from "@/i18n";
import { backendUrl } from "@/lib/config";
import { formatTime } from "@/lib/format";
import { haptic } from "@/lib/haptics";
import { AUTO_QUALITY, type Quality } from "@/lib/local-player/engine";
import { errorMessage } from "@/lib/query";
import { cn } from "@/lib/utils";
import { useLocalPlayerStore, type LocalMedia, type LocalSource } from "@/stores/local-player-store";
import { FullscreenControls } from "./local-fullscreen-controls";
import { LiveBadge } from "./live-badge";
import { SkipButton } from "./now-playing";
import { PlayPauseButton } from "./play-pause-button";
import { SeekBar } from "./seek-bar";
import { TrackPicker } from "./track-picker";
import { VolumeControl } from "./volume-control";

const FULL = "calc(100dvh - env(safe-area-inset-top) - 0.5rem)";

type LockableOrientation = ScreenOrientation & { lock?: (orientation: string) => Promise<void> };

/** Phones: turn a landscape video sideways while full screen (Android Chrome; a no-op elsewhere). */
function lockLandscape() {
  if (!window.matchMedia?.("(pointer: coarse)").matches) return;
  (screen.orientation as LockableOrientation | undefined)?.lock?.("landscape").catch(() => {});
}

function unlockOrientation() {
  try {
    screen.orientation?.unlock?.();
  } catch {
    /* not locked / unsupported */
  }
}

function bitrateName(bps: number): string {
  return bps >= 1e6 ? `${(bps / 1e6).toFixed(1)} Mbps` : `${Math.round(bps / 1e3)} kbps`;
}

/**
 * "1080p"; "360p · 1.2 Mbps" when several renditions share that height; the bitrate alone when the
 * rendition has no height (audio-only, odd manifests).
 */
export function qualityName(q: Quality, all: Quality[] = [q]): string {
  if (!q.height) return bitrateName(q.bitrate);
  const twins = all.filter((o) => o.height === q.height).length > 1;
  return twins ? `${q.height}p · ${bitrateName(q.bitrate)}` : `${q.height}p`;
}

/** The "Watch here" player, mounted once by the app shell and opened through `openLocalPlayer()`. */
export function LocalPlayerSheet() {
  const t = useT();
  const media = useLocalPlayerStore((s) => s.media);
  const close = useLocalPlayerStore((s) => s.close);
  const isDesktop = useIsDesktop();
  return (
    <Drawer
      open={!!media}
      onOpenChange={(open) => !open && close()}
      swipeDirection={isDesktop ? "right" : "down"}
      showSwipeHandle={!isDesktop}
    >
      <DrawerContent
        className="sm:data-[swipe-axis=x]:[--drawer-content-width:36rem]"
        style={isDesktop ? undefined : ({ height: FULL, ["--drawer-content-max-height" as string]: FULL } as React.CSSProperties)}
      >
        <DrawerTitle className="sr-only">{media?.title ?? t("localPlayer.watchHere")}</DrawerTitle>
        {media && <LocalPlayerContent media={media} onClose={close} />}
      </DrawerContent>
    </Drawer>
  );
}

/** Resolves `media.source` when it is a function (e.g. a resolver call), once per media. */
function useSource(media: LocalMedia): { source: LocalSource | null; error: unknown } {
  const direct = typeof media.source === "function" ? null : media.source;
  const [resolved, setResolved] = useState<{ for: LocalMedia; source: LocalSource | null; error: unknown } | null>(null);
  useEffect(() => {
    if (typeof media.source !== "function") return;
    const ctrl = new AbortController();
    media
      .source(ctrl.signal)
      .then((source) => !ctrl.signal.aborted && setResolved({ for: media, source, error: null }))
      .catch((error) => !ctrl.signal.aborted && setResolved({ for: media, source: null, error }));
    return () => ctrl.abort();
  }, [media]);
  if (direct) return { source: direct, error: null };
  return resolved?.for === media ? { source: resolved.source, error: resolved.error } : { source: null, error: null };
}

export function LocalPlayerContent({ media, onClose }: { media: LocalMedia; onClose?: () => void }) {
  const t = useT();
  const videoRef = useRef<HTMLVideoElement>(null);
  const [box, setBox] = useState<HTMLDivElement | null>(null);
  const [attempt, setAttempt] = useState(0);
  const [fullscreen, setFullscreen] = useState(false);
  const { source, error: sourceError } = useSource(media);
  const v = useLocalVideo(videoRef, source, attempt, media.startAt);
  const { state } = v;
  const { info } = state;

  const live = info.live || state.duration === Infinity;
  const failed = state.status === "error" || !!sourceError;
  const ready = state.status === "ready" && !failed;
  const vod = !live && Number.isFinite(state.duration) && state.duration > 0;
  const behind = live && state.edge != null ? Math.max(0, state.edge - state.time) : 0;
  const pipSupported = typeof document !== "undefined" && "pictureInPictureEnabled" in document && document.pictureInPictureEnabled;

  useEffect(() => {
    const onChange = () => {
      const on = !!box && document.fullscreenElement === box;
      setFullscreen(on);
      if (!on) unlockOrientation();
    };
    document.addEventListener("fullscreenchange", onChange);
    return () => document.removeEventListener("fullscreenchange", onChange);
  }, [box]);

  // leaving the sheet while full screen (e.g. "Send to TV") must not leave the page stuck full screen
  useEffect(
    () => () => {
      if (box && document.fullscreenElement === box) void document.exitFullscreen().catch(() => {});
    },
    [box],
  );

  const exitFullscreen = () => {
    if (document.fullscreenElement) void document.exitFullscreen().catch(() => {});
  };

  const toggleFullscreen = () => {
    haptic();
    const video = videoRef.current as (HTMLVideoElement & { webkitEnterFullscreen?: () => void }) | null;
    if (document.fullscreenElement) return exitFullscreen();
    if (box?.requestFullscreen) {
      void box
        .requestFullscreen({ navigationUI: "hide" })
        .then(() => {
          box.focus();
          if (video && video.videoWidth > video.videoHeight) lockLandscape();
        })
        .catch(() => video?.webkitEnterFullscreen?.());
    } else video?.webkitEnterFullscreen?.(); // iPhone Safari: only the <video> itself can go full screen (native UI)
  };

  const sendToTv = media.onCast
    ? () => {
        haptic();
        exitFullscreen();
        videoRef.current?.pause();
        media.onCast?.(vod ? state.time : null);
        onClose?.();
      }
    : undefined;

  const togglePip = () => {
    haptic();
    const video = videoRef.current;
    if (!video) return;
    if (document.pictureInPictureElement) void document.exitPictureInPicture();
    else void video.requestPictureInPicture().catch(() => {});
  };

  /** Quality + track menus; full screen they must portal into the full-screen element to be visible. */
  const menus = (container: HTMLElement | null) => (
    <>
      {info.qualities.length > 1 && (
        <QualityMenu qualities={info.qualities} current={info.quality} onChange={(id) => v.setQuality(id)} container={container} />
      )}
      <TrackPicker tracks={info.tracks} activeIds={info.activeTrackIds} onChange={(ids) => v.setTracks(ids)} container={container} />
    </>
  );

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
          <p className="truncate text-sm font-semibold">{t("localPlayer.thisDevice")}</p>
        </div>
        {menus(null)}
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto overscroll-contain px-5 pt-5 pb-[max(env(safe-area-inset-bottom),1.25rem)]">
        <div className="mx-auto flex max-w-xl flex-col gap-6">
          <div
            ref={setBox}
            tabIndex={-1}
            className={cn(
              "relative aspect-video w-full overflow-hidden bg-black outline-none",
              fullscreen ? "rounded-none" : "rounded-2xl shadow-2xl shadow-black/40",
            )}
          >
            <video
              ref={videoRef}
              data-testid="local-video"
              className={cn("size-full object-contain", failed && "invisible")}
              poster={media.poster ? backendUrl(media.poster) : undefined}
              playsInline
              onClick={() => !fullscreen && v.toggle()}
              onDoubleClick={toggleFullscreen}
            />
            {fullscreen && !failed && (
              <FullscreenControls
                title={media.title || t("player.untitled")}
                subtitle={media.subtitle}
                live={live}
                vod={vod}
                ready={ready}
                paused={state.paused}
                buffering={state.buffering}
                time={state.time}
                duration={state.duration}
                behind={behind}
                volume={state.volume}
                muted={state.muted}
                menus={menus(box)}
                onToggle={v.toggle}
                onSeek={v.seek}
                onSkip={v.seekRelative}
                onGoLive={v.goLive}
                onVolume={v.setVolume}
                onMuted={v.setMuted}
                onExit={exitFullscreen}
                onPip={pipSupported ? togglePip : undefined}
                onCast={sendToTv}
              />
            )}
            {!failed && (state.status === "loading" || (state.buffering && !state.paused)) && (
              <div className="pointer-events-none absolute inset-0 grid place-items-center">
                <Loader2 className="size-8 animate-spin text-white/80" />
              </div>
            )}
            {failed && (
              <div role="alert" className="absolute inset-0 grid place-items-center bg-black p-4 text-center text-xs text-white/80">
                <div className="flex flex-col items-center gap-2">
                  <AlertTriangle className="size-5" />
                  {sourceError ? errorMessage(sourceError, t("localPlayer.error")) : t("localPlayer.error")}
                  <button
                    type="button"
                    onClick={() => setAttempt((n) => n + 1)}
                    className="mt-1 inline-flex h-9 items-center gap-1.5 rounded-full bg-white/15 px-4 text-xs font-medium text-white active:bg-white/25"
                  >
                    <RotateCw className="size-3.5" /> {t("common.retry")}
                  </button>
                </div>
              </div>
            )}
          </div>

          <div className="space-y-1">
            <div className="flex items-start gap-2">
              <h2 className="line-clamp-2 flex-1 text-xl font-bold tracking-tight">{media.title || t("player.untitled")}</h2>
              {live && <LiveBadge className="mt-1" dim={behind > 10} />}
            </div>
            <p className="truncate text-sm text-muted-foreground">
              {!ready && !failed ? t("player.loading") : (media.subtitle ?? t("localPlayer.thisDevice"))}
            </p>
          </div>

          {vod ? (
            <SeekBar position={state.time} duration={state.duration} disabled={!ready} onSeek={v.seek} />
          ) : live ? (
            <div className="flex items-center justify-between gap-2">
              <span className="font-mono text-xs text-muted-foreground tabular-nums">
                {behind > 5 ? `-${formatTime(behind)}` : formatTime(state.time)}
              </span>
              <Button variant="secondary" size="sm" onClick={v.goLive} disabled={!ready} className="gap-1.5">
                <Radio className="size-4 text-live" />
                {t("player.goLive")}
              </Button>
            </div>
          ) : null}

          <div className="flex items-center justify-center gap-1">
            <SkipButton seconds={-10} onClick={() => v.seekRelative(-10)} disabled={!ready} />
            <PlayPauseButton
              size="lg"
              state={state.status === "loading" || (state.buffering && !state.paused) ? "BUFFERING" : state.paused ? "PAUSED" : "PLAYING"}
              onToggle={v.toggle}
              disabled={failed}
              className="mx-3"
            />
            <SkipButton seconds={10} onClick={() => v.seekRelative(10)} disabled={!ready || (live && behind < 1)} />
          </div>

          <VolumeControl
            level={state.volume}
            muted={state.muted}
            onCommand={(action, value) => {
              if (action === "mute") v.setMuted(true);
              else if (action === "unmute") v.setMuted(false);
              else if (action === "volume" && value != null) v.setVolume(value);
            }}
          />

          <div className={cn("grid gap-2", media.onCast ? "grid-cols-[1fr_auto_auto]" : "grid-cols-2")}>
            {media.onCast && (
              <Button
                size="lg"
                className="gap-2"
                onClick={sendToTv}
              >
                <Cast className="size-5" /> {t("localPlayer.sendToTv")}
              </Button>
            )}
            <Button
              variant="secondary"
              size="lg"
              onClick={toggleFullscreen}
              disabled={failed}
              aria-label={t("localPlayer.fullscreen")}
              className="gap-2"
            >
              <Maximize className="size-4" />
              {!media.onCast && t("localPlayer.fullscreen")}
            </Button>
            {pipSupported && (
              <Button
                variant="secondary"
                size="lg"
                onClick={togglePip}
                disabled={!ready}
                aria-label={t("localPlayer.pip")}
                className="gap-2"
              >
                <PictureInPicture2 className="size-4" />
                {!media.onCast && t("localPlayer.pip")}
              </Button>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

function QualityMenu({
  qualities,
  current,
  onChange,
  container,
}: {
  qualities: Quality[];
  current: number;
  onChange: (id: number) => void;
  container?: HTMLElement | null;
}) {
  const t = useT();
  const sorted = [...qualities].sort((a, b) => (b.height ?? 0) - (a.height ?? 0) || b.bitrate - a.bitrate);
  return (
    <DropdownMenu>
      <DropdownMenuTrigger render={<Button variant="ghost" size="icon" aria-label={t("localPlayer.quality")} />}>
        <Settings2 className={current === AUTO_QUALITY ? "size-5" : "size-5 text-primary"} />
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="w-48" container={container}>
        <DropdownMenuGroup>
          <DropdownMenuLabel>{t("localPlayer.quality")}</DropdownMenuLabel>
          <DropdownMenuItem onClick={() => onChange(AUTO_QUALITY)}>
            <span className="flex-1">{t("localPlayer.auto")}</span>
            {current === AUTO_QUALITY && <Check className="size-4" />}
          </DropdownMenuItem>
          {sorted.map((q) => (
            <DropdownMenuItem key={q.id} onClick={() => onChange(q.id)}>
              <span className="flex-1 tabular-nums">{qualityName(q, qualities)}</span>
              {current === q.id && <Check className="size-4" />}
            </DropdownMenuItem>
          ))}
        </DropdownMenuGroup>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
