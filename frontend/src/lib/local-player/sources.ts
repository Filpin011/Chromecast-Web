/** Builders for the "Watch here" player: what to play for a captured stream or a playlist channel. */
import { toast } from "sonner";
import { t } from "@/i18n";
import { api } from "@/lib/api";
import type { CapturedStream, Channel, ControlAction, PlayerState, SourceKind } from "@/lib/api/types";
import { channelInput } from "@/lib/channels";
import { errorMessage } from "@/lib/query";
import { useAppStore } from "@/stores/app-store";
import type { LocalMedia, LocalSource } from "@/stores/local-player-store";
import { useUiStore } from "@/stores/ui-store";

/** Below this, "carry on from here" isn't worth a seek. */
const MIN_RESUME = 5;

async function control(deviceId: string, action: ControlAction, value?: number) {
  useAppStore.getState().applyPlayer(await api.player.control(deviceId, action, value));
}

/** After a cast started (`p`), carry on from the position reached on this device (on-demand only). */
export async function seekAfterCast(p: PlayerState | null, resumeAt: number | null) {
  if (!p || resumeAt == null || resumeAt < MIN_RESUME) return;
  try {
    await control(p.device_id, "seek", resumeAt);
  } catch (e) {
    toast.error(errorMessage(e, t("player.commandFailed")));
  }
}

/**
 * What the TV is playing, to continue on this device ("Watch on this device" in Now Playing). The TV is
 * paused, not stopped: "Send to TV" then just resumes it there, at the position reached here.
 */
export function tvMedia(deviceId: string, player: PlayerState, position: number): LocalMedia | null {
  if (!player.original_input) return null;
  const live = player.stream_type === "LIVE";
  return {
    title: player.title ?? player.original_input,
    subtitle: null,
    poster: player.thumbnail,
    startAt: live ? null : position,
    source: resolvedSource(player.original_input),
    onCast: (resumeAt) => {
      void (async () => {
        try {
          if (live) await control(deviceId, "go_live");
          else if (resumeAt != null) await control(deviceId, "seek", resumeAt);
          await control(deviceId, "play");
          useUiStore.getState().setNowPlayingOpen(true);
        } catch (e) {
          toast.error(errorMessage(e, t("player.commandFailed")));
        }
      })();
    },
  };
}

const MIME_BY_KIND: Partial<Record<CapturedStream["kind"], string>> = {
  hls: "application/x-mpegURL",
  dash: "application/dash+xml",
};

/** Ask the resolver for a same-origin `preview_url` (it goes through the backend proxy, with the headers). */
export function resolvedSource(input: string, kind?: SourceKind) {
  return async (signal: AbortSignal): Promise<LocalSource> => {
    const r = await api.resolver.resolve(input, kind, signal);
    if (r.type !== "media" || !r.media.preview_url) throw new Error();
    return { src: r.media.preview_url, mimeType: r.media.mime_type };
  };
}

export function capturedMedia(
  stream: CapturedStream,
  opts: { title?: string | null; poster?: string | null; onCast?: LocalMedia["onCast"] } = {},
): LocalMedia {
  // The detected kind is the reliable signal: many streams have no extension (`/token-…`) or a disguised one.
  const mimeType = MIME_BY_KIND[stream.kind] ?? stream.mime_type;
  let host: string | null = null;
  try {
    host = new URL(stream.page_url).hostname;
  } catch {
    /* keep null */
  }
  return {
    title: opts.title || stream.title || host || stream.url,
    subtitle: [stream.quality, host].filter(Boolean).join(" · ") || null,
    poster: opts.poster ?? stream.thumbnail ?? null,
    source: stream.preview_url ? { src: stream.preview_url, mimeType } : resolvedSource(stream.url, "direct"),
    onCast: opts.onCast,
  };
}

export function channelMedia(channel: Channel, opts: { onCast?: LocalMedia["onCast"] } = {}): LocalMedia {
  return {
    title: channel.name,
    subtitle: channel.group,
    poster: channel.logo,
    source: resolvedSource(channelInput(channel)),
    onCast: opts.onCast,
  };
}
