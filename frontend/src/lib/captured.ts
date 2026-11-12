import type { CapturedKind, CapturedStream } from "@/lib/api/types";

/** Insert or replace a captured stream by id (keeps original order for existing ones). */
export function upsertCaptured(list: CapturedStream[], s: CapturedStream): CapturedStream[] {
  const i = list.findIndex((x) => x.id === s.id);
  if (i === -1) return [...list, s];
  const next = list.slice();
  next[i] = { ...list[i], ...s };
  return next;
}

const KIND_WEIGHT: Record<CapturedKind, number> = { hls: 3, dash: 2, progressive: 1, unknown: 0 };

/** Best candidates first: backend score, then resolution, HLS master, kind, most recent. */
export function rankCaptured(list: CapturedStream[]): CapturedStream[] {
  return list
    .map((s, idx) => ({ s, idx }))
    .sort((a, b) => {
      const d =
        (b.s.score ?? 0) - (a.s.score ?? 0) ||
        (b.s.height ?? 0) - (a.s.height ?? 0) ||
        Number(b.s.is_master === true) - Number(a.s.is_master === true) ||
        KIND_WEIGHT[b.s.kind] - KIND_WEIGHT[a.s.kind] ||
        Date.parse(b.s.detected_at) - Date.parse(a.s.detected_at);
      return d || a.idx - b.idx;
    })
    .map((x) => x.s);
}

export const KIND_LABEL: Record<CapturedKind, string> = {
  hls: "HLS",
  dash: "DASH",
  progressive: "MP4",
  unknown: "?",
};

/** Derive a human quality label when the backend didn't provide one. */
export function qualityLabel(s: Pick<CapturedStream, "quality" | "height">): string | null {
  if (s.quality) return s.quality;
  const h = s.height ?? 0;
  if (!h) return null;
  if (h >= 2160) return "4K UHD";
  if (h >= 1440) return "1440p QHD";
  if (h >= 1080) return "1080p FHD";
  if (h >= 720) return "720p HD";
  return `${h}p SD`;
}
