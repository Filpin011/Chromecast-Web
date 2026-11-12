import type { MessageKey } from "@/i18n";
import type { SourceKind } from "@/lib/api/types";

export type InputKind = "empty" | "url" | "m3u" | "youtube" | "stream" | "invalid";

export interface DetectedInput {
  kind: InputKind;
  /** Normalised value to send to the backend. */
  value: string;
  /** Suggested backend `kind`, if we are confident. Otherwise let the backend auto-detect. */
  sourceKind?: SourceKind;
}

const YT_RE = /^(https?:\/\/)?((www|m|music)\.)?(youtube\.com|youtu\.be)\//i;
const STREAM_RE = /\.(m3u8|mpd|mp4|m4v|webm|mkv|ts|flv|mov|mp3|aac)(\?|#|$)/i;
const M3U_RE = /\.m3u(\?|#|$)/i;

/** Classify what the user typed/pasted into the smart input. Pure & cheap (runs on every keystroke). */
export function detectInput(raw: string): DetectedInput {
  const value = raw.trim();
  if (!value) return { kind: "empty", value };
  if (value.startsWith("#EXTM3U")) return { kind: "m3u", value, sourceKind: "m3u" };

  let candidate = value;
  if (!/^[a-z][a-z0-9+.-]*:\/\//i.test(candidate)) {
    // bare domain like "example.com/live" → assume https
    if (/^[\w-]+(\.[\w-]+)+(:\d+)?(\/\S*)?$/.test(candidate)) candidate = `https://${candidate}`;
    else return { kind: "invalid", value };
  }
  let url: URL;
  try {
    url = new URL(candidate);
  } catch {
    return { kind: "invalid", value };
  }
  if (!["http:", "https:", "rtmp:", "rtsp:", "udp:", "rtp:"].includes(url.protocol)) {
    return { kind: "invalid", value };
  }
  const href = url.toString();
  if (YT_RE.test(href)) return { kind: "youtube", value: href, sourceKind: "ytdlp" };
  if (M3U_RE.test(url.pathname) || /[?&](type|output)=m3u(_plus)?\b/i.test(url.search)) {
    return { kind: "m3u", value: href, sourceKind: "m3u" };
  }
  if (STREAM_RE.test(url.pathname) || url.protocol !== "http:" && url.protocol !== "https:") {
    return { kind: "stream", value: href, sourceKind: "direct" };
  }
  return { kind: "url", value: href };
}

/** Dictionary key of each detected kind's label (none for empty input). */
export const INPUT_KIND_LABEL: Record<Exclude<InputKind, "empty">, MessageKey> = {
  url: "input.kind.url",
  m3u: "input.kind.m3u",
  youtube: "input.kind.youtube",
  stream: "input.kind.stream",
  invalid: "input.kind.invalid",
};

/**
 * Whether a typed (not pasted / submitted) input may be resolved automatically after a pause.
 * Only cheap, unambiguous inputs: a direct stream URL or an M3U. Web pages and yt-dlp sites start a costly
 * server-side resolve (headless browser, up to ~25s), so a half-typed URL must not trigger them: they wait
 * for Enter / the arrow button. Pasted input is complete and is resolved right away.
 */
export function autoResolvesWhileTyping(d: DetectedInput): boolean {
  return d.kind === "stream" || d.kind === "m3u";
}
