/**
 * Playback engines for the local ("Watch here") player: hls.js for HLS, dash.js for
 * DASH, the plain <video> element for progressive files. Both libraries are imported lazily, only when a
 * stream of that kind is opened.
 *
 * Every engine reports the same shape (`EngineInfo`) so the UI doesn't care which one is playing.
 * Engines only attach the source: starting playback (and the muted-autoplay fallback) is the caller's job.
 */
import type { MediaTrack } from "@/lib/api/types";
import { canPlayNativeHls, isDashSource, isHlsSource } from "@/lib/media";

/** Text tracks get ids from here on, so audio (0..) and subtitle ids never collide in one list. */
export const TEXT_ID_BASE = 1000;
/** `EngineInfo.quality` when the engine picks the rendition by itself (ABR). */
export const AUTO_QUALITY = -1;

export interface Quality {
  id: number;
  height: number | null;
  bitrate: number;
}

export interface EngineInfo {
  /** Live/dynamic stream (no fixed duration; "Go live" makes sense). */
  live: boolean;
  qualities: Quality[];
  quality: number;
  /** Audio and subtitle tracks, in the shape the Now Playing track picker already uses. */
  tracks: MediaTrack[];
  activeTrackIds: number[];
}

export interface Engine {
  kind: "hls" | "dash" | "native";
  setQuality(id: number): void;
  setTracks(ids: number[]): void;
  goLive(): void;
  destroy(): void;
}

export interface EngineEvents {
  onInfo: (info: EngineInfo) => void;
  onFatal: (message?: string) => void;
}

export const EMPTY_INFO: EngineInfo = { live: false, qualities: [], quality: AUTO_QUALITY, tracks: [], activeTrackIds: [] };

export type EngineKind = Engine["kind"];

/**
 * HLS always goes to hls.js first, even where the browser plays HLS natively (Safari, recent Chrome/Edge):
 * only hls.js exposes renditions and tracks. `attachHls` falls back to the element when MSE is missing
 * (older iPhones).
 */
export function engineKindFor(url: string, mime: string | null | undefined): EngineKind {
  if (isDashSource(url, mime)) return "dash";
  if (isHlsSource(url, mime)) return "hls";
  return "native";
}

/** Live edge of the seekable range (minus a small safety margin), or null when not known yet. */
export function liveEdge(video: HTMLVideoElement, margin = 3): number | null {
  const r = video.seekable;
  if (!r || r.length === 0) return null;
  return Math.max(r.start(r.length - 1), r.end(r.length - 1) - margin);
}

export async function attachEngine(
  video: HTMLVideoElement,
  url: string,
  mime: string | null | undefined,
  events: EngineEvents,
): Promise<Engine> {
  const kind = engineKindFor(url, mime);
  if (kind === "hls") return attachHls(video, url, events);
  if (kind === "dash") return attachDash(video, url, events);
  return attachNative(video, url, events);
}

// ------------------------------------------------------------------ native <video>

function attachNative(video: HTMLVideoElement, url: string, { onInfo }: EngineEvents): Engine {
  const report = () => onInfo({ ...EMPTY_INFO, live: video.duration === Infinity });
  video.addEventListener("loadedmetadata", report);
  video.addEventListener("durationchange", report);
  video.src = url;
  return {
    kind: "native",
    setQuality: () => {},
    setTracks: () => {},
    goLive: () => {
      const edge = liveEdge(video);
      if (edge != null) video.currentTime = edge;
    },
    destroy: () => {
      video.removeEventListener("loadedmetadata", report);
      video.removeEventListener("durationchange", report);
      video.removeAttribute("src");
      video.load?.();
    },
  };
}

// ------------------------------------------------------------------ hls.js

async function attachHls(video: HTMLVideoElement, url: string, events: EngineEvents): Promise<Engine> {
  const { default: Hls } = await import("hls.js");
  if (!Hls.isSupported()) {
    if (canPlayNativeHls(video)) return attachNative(video, url, events);
    events.onFatal();
    return { kind: "hls", setQuality: () => {}, setTracks: () => {}, goLive: () => {}, destroy: () => {} };
  }
  const { onInfo, onFatal } = events;
  const hls = new Hls({
    lowLatencyMode: true,
    backBufferLength: 60,
    // hls.js assumes 500 kbps until it has measured something, so "Auto" starts at 240p and climbs
    // slowly. This plays on a home LAN/Wi-Fi: start from a realistic estimate, ABR still steps down.
    abrEwmaDefaultEstimate: 5_000_000,
  });
  let live = false;
  // On top of hls.js's own per-request retries: a few restarts after fatal network errors (a live edge
  // that hiccups, a slow upstream) and the documented media-error recovery (recover, then swap the audio
  // codec and recover). The counters reset once a fragment is buffered again.
  let networkRestarts = 0;
  let mediaRecoveries = 0;
  let restartTimer: ReturnType<typeof setTimeout> | undefined;

  const info = (): EngineInfo => {
    const tracks: MediaTrack[] = [
      ...hls.audioTracks.map((t, i) => ({ id: i, type: "AUDIO" as const, name: t.name || null, language: t.lang || null })),
      ...hls.subtitleTracks.map((t, i) => ({
        id: TEXT_ID_BASE + i,
        type: "TEXT" as const,
        name: t.name || null,
        language: t.lang || null,
      })),
    ];
    const active: number[] = [];
    if (hls.audioTrack >= 0 && hls.audioTracks.length) active.push(hls.audioTrack);
    if (hls.subtitleTrack >= 0) active.push(TEXT_ID_BASE + hls.subtitleTrack);
    return {
      live,
      qualities: hls.levels.map((l, i) => ({ id: i, height: l.height || null, bitrate: l.bitrate })),
      quality: hls.autoLevelEnabled ? AUTO_QUALITY : hls.manualLevel,
      tracks,
      activeTrackIds: active,
    };
  };
  const report = () => onInfo(info());

  hls.on(Hls.Events.MANIFEST_PARSED, report);
  hls.on(Hls.Events.LEVEL_LOADED, (_e, data) => {
    if (data.details.live !== live) {
      live = data.details.live;
      report();
    }
  });
  for (const ev of [
    Hls.Events.LEVEL_SWITCHED,
    Hls.Events.AUDIO_TRACKS_UPDATED,
    Hls.Events.AUDIO_TRACK_SWITCHED,
    Hls.Events.SUBTITLE_TRACKS_UPDATED,
    Hls.Events.SUBTITLE_TRACK_SWITCH,
  ]) {
    hls.on(ev, report);
  }
  hls.on(Hls.Events.FRAG_BUFFERED, () => {
    networkRestarts = 0;
    mediaRecoveries = 0;
  });
  hls.on(Hls.Events.ERROR, (_e, data) => {
    if (!data.fatal) return;
    console.warn("[local-player] hls.js fatal error", data.type, data.details, data.response?.code ?? "");
    if (data.type === Hls.ErrorTypes.NETWORK_ERROR && networkRestarts < 3) {
      networkRestarts += 1;
      clearTimeout(restartTimer);
      restartTimer = setTimeout(() => hls.startLoad(), 1000 * networkRestarts);
      return;
    }
    if (data.type === Hls.ErrorTypes.MEDIA_ERROR && mediaRecoveries < 2) {
      if (mediaRecoveries === 1) hls.swapAudioCodec();
      mediaRecoveries += 1;
      hls.recoverMediaError();
      return;
    }
    onFatal(data.details);
  });

  hls.subtitleDisplay = true;
  hls.loadSource(url);
  hls.attachMedia(video);

  return {
    kind: "hls",
    setQuality: (id) => {
      hls.currentLevel = id; // -1 = auto
      report();
    },
    setTracks: (ids) => {
      const audio = ids.find((id) => id < TEXT_ID_BASE);
      const text = ids.find((id) => id >= TEXT_ID_BASE);
      if (audio != null && audio !== hls.audioTrack) hls.audioTrack = audio;
      hls.subtitleTrack = text == null ? -1 : text - TEXT_ID_BASE;
      report();
    },
    goLive: () => {
      const pos = hls.liveSyncPosition ?? liveEdge(video);
      if (pos != null) video.currentTime = pos;
      video.play().catch(() => {});
    },
    destroy: () => {
      clearTimeout(restartTimer);
      hls.destroy();
      video.removeAttribute("src");
      video.load?.();
    },
  };
}

// ------------------------------------------------------------------ dash.js

async function attachDash(video: HTMLVideoElement, url: string, { onInfo, onFatal }: EngineEvents): Promise<Engine> {
  const dashjs = await import("dashjs");
  if (!dashjs.supportsMediaSource()) {
    onFatal();
    return { kind: "dash", setQuality: () => {}, setTracks: () => {}, goLive: () => {}, destroy: () => {} };
  }
  const player = dashjs.MediaPlayer().create();
  let manual = AUTO_QUALITY;

  const info = (): EngineInfo => {
    const audio = player.getTracksFor("audio");
    const text = player.getTracksFor("text");
    const curAudio = player.getCurrentTrackFor("audio");
    const textIdx = player.getCurrentTextTrackIndex();
    const label = (m: { labels: { text: string }[] }) => m.labels?.[0]?.text || null;
    const tracks: MediaTrack[] = [
      ...audio.map((m, i) => ({ id: i, type: "AUDIO" as const, name: label(m), language: m.lang })),
      ...text.map((m, i) => ({ id: TEXT_ID_BASE + i, type: "TEXT" as const, name: label(m), language: m.lang })),
    ];
    const active: number[] = [];
    const a = curAudio ? audio.indexOf(curAudio) : -1;
    if (a >= 0) active.push(a);
    if (textIdx >= 0) active.push(TEXT_ID_BASE + textIdx);
    return {
      live: player.isDynamic(),
      qualities: player
        .getRepresentationsByType("video")
        .map((r, i) => ({ id: i, height: r.height || null, bitrate: r.bandwidth })),
      quality: manual,
      tracks,
      activeTrackIds: active,
    };
  };
  const report = () => onInfo(info());
  const E = dashjs.MediaPlayer.events;
  player.on(E.STREAM_INITIALIZED, report);
  player.on(E.TRACK_CHANGE_RENDERED, report);
  player.on(E.ERROR, (e) => onFatal(String((e as { error?: { message?: string } }).error?.message ?? "")));

  player.initialize(video, url, false);
  player.enableText(false);

  return {
    kind: "dash",
    setQuality: (id) => {
      manual = id;
      const auto = id === AUTO_QUALITY;
      player.updateSettings({ streaming: { abr: { autoSwitchBitrate: { video: auto } } } });
      const rep = auto ? null : player.getRepresentationsByType("video")[id];
      if (rep) player.setRepresentationForTypeById("video", rep.id, true);
      report();
    },
    setTracks: (ids) => {
      const audio = ids.find((id) => id < TEXT_ID_BASE);
      const text = ids.find((id) => id >= TEXT_ID_BASE);
      const audioTrack = audio == null ? null : player.getTracksFor("audio")[audio];
      if (audioTrack) player.setCurrentTrack(audioTrack);
      if (text == null) player.enableText(false);
      else {
        player.enableText(true);
        player.setTextTrack(text - TEXT_ID_BASE);
      }
      report();
    },
    goLive: () => {
      player.seekToOriginalLive();
      video.play().catch(() => {});
    },
    destroy: () => {
      player.destroy();
      video.removeAttribute("src");
      video.load?.();
    },
  };
}
