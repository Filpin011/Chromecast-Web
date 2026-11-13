"use client";

import { useCallback, useEffect, useRef, useState, type RefObject } from "react";
import { backendUrl } from "@/lib/config";
import { attachEngine, EMPTY_INFO, liveEdge, type Engine, type EngineInfo } from "@/lib/local-player/engine";
import type { LocalSource } from "@/stores/local-player-store";

export type LocalStatus = "loading" | "ready" | "error";

export interface LocalVideoState {
  status: LocalStatus;
  paused: boolean;
  buffering: boolean;
  time: number;
  /** Seconds, or Infinity/NaN for live streams. */
  duration: number;
  /** End of the seekable range (the live edge on live streams), null until known. */
  edge: number | null;
  volume: number;
  muted: boolean;
  info: EngineInfo;
}

const INITIAL: LocalVideoState = {
  status: "loading",
  paused: true,
  buffering: true,
  time: 0,
  duration: NaN,
  edge: null,
  volume: 1,
  muted: false,
  info: EMPTY_INFO,
};

/**
 * Drives a <video> element for the local player: attaches the right engine for `source`, mirrors the
 * element's state into React and exposes the commands the controls need. A new `attempt` tears the
 * engine down and loads the source again ("Retry").
 */
export function useLocalVideo(
  ref: RefObject<HTMLVideoElement | null>,
  source: LocalSource | null,
  attempt: number,
  startAt?: number | null,
) {
  const [state, setState] = useState<LocalVideoState>(INITIAL);
  const engine = useRef<Engine | null>(null);
  const patch = useCallback((p: Partial<LocalVideoState>) => setState((s) => ({ ...s, ...p })), []);

  // engine lifecycle
  useEffect(() => {
    const video = ref.current;
    if (!video || !source) return;
    let destroyed = false;
    const url = backendUrl(source.src);
    const reset = setTimeout(() => !destroyed && setState((s) => ({ ...INITIAL, volume: s.volume, muted: s.muted })), 0);

    // Start as soon as there is something to show; if the browser refuses audible autoplay, start muted.
    const onCanPlay = () => {
      video.removeEventListener("canplay", onCanPlay);
      video.play().catch(() => {
        if (destroyed) return;
        video.muted = true;
        video.play().catch(() => {});
      });
    };
    video.addEventListener("canplay", onCanPlay);
    // Resume point (e.g. coming from the TV): only for on-demand media, once the duration is known.
    const onMeta = () => {
      video.removeEventListener("loadedmetadata", onMeta);
      if (startAt && startAt > 0 && Number.isFinite(video.duration) && startAt < video.duration - 1) {
        video.currentTime = startAt;
      }
    };
    video.addEventListener("loadedmetadata", onMeta);

    attachEngine(video, url, source.mimeType, {
      onInfo: (info) => !destroyed && patch({ info }),
      onFatal: () => !destroyed && patch({ status: "error" }),
    })
      .then((e) => {
        if (destroyed) e.destroy();
        else engine.current = e;
      })
      .catch(() => !destroyed && patch({ status: "error" }));

    return () => {
      destroyed = true;
      clearTimeout(reset);
      video.removeEventListener("canplay", onCanPlay);
      video.removeEventListener("loadedmetadata", onMeta);
      engine.current?.destroy();
      engine.current = null;
    };
  }, [ref, source, attempt, startAt, patch]);

  // element → state
  useEffect(() => {
    const video = ref.current;
    if (!video) return;
    const sync = () =>
      patch({
        paused: video.paused,
        time: video.currentTime,
        duration: video.duration,
        edge: liveEdge(video, 0),
        volume: video.volume,
        muted: video.muted,
      });
    const handlers: [string, () => void][] = [
      ["play", sync],
      ["pause", sync],
      ["timeupdate", sync],
      ["durationchange", sync],
      ["volumechange", sync],
      ["seeked", sync],
      ["waiting", () => patch({ buffering: true })],
      ["playing", () => patch({ buffering: false, status: "ready", paused: false })],
      ["canplay", () => patch({ buffering: false, status: "ready" })],
      ["error", () => patch({ status: "error" })],
    ];
    for (const [ev, fn] of handlers) video.addEventListener(ev, fn);
    return () => {
      for (const [ev, fn] of handlers) video.removeEventListener(ev, fn);
    };
  }, [ref, patch]);

  const video = () => ref.current;
  const commands = {
    toggle: () => {
      const v = video();
      if (!v) return;
      if (v.paused) v.play().catch(() => {});
      else v.pause();
    },
    seek: (seconds: number) => {
      const v = video();
      if (v) v.currentTime = Math.max(0, seconds);
    },
    seekRelative: (delta: number) => {
      const v = video();
      if (!v) return;
      const max = v.seekable.length ? v.seekable.end(v.seekable.length - 1) : v.duration;
      const min = v.seekable.length ? v.seekable.start(0) : 0;
      const target = v.currentTime + delta;
      v.currentTime = Number.isFinite(max) ? Math.min(Math.max(min, target), max) : Math.max(min, target);
    },
    setVolume: (level: number) => {
      const v = video();
      if (!v) return;
      v.volume = Math.min(1, Math.max(0, level));
      if (level > 0) v.muted = false;
    },
    setMuted: (muted: boolean) => {
      const v = video();
      if (v) v.muted = muted;
    },
    goLive: () => engine.current?.goLive(),
    setQuality: (id: number) => engine.current?.setQuality(id),
    setTracks: (ids: number[]) => engine.current?.setTracks(ids),
  };

  return { state, ...commands };
}
