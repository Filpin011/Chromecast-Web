import type { Locale, MessageKey } from "@/i18n";
import { currentLocale, formatNumber, formatRelativeTime } from "@/i18n";
import type { SourceKind } from "@/lib/api/types";

export function formatTime(totalSeconds: number | null | undefined): string {
  if (totalSeconds == null || !Number.isFinite(totalSeconds) || totalSeconds < 0) return "0:00";
  const s = Math.floor(totalSeconds);
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  const sec = s % 60;
  const ss = String(sec).padStart(2, "0");
  return h > 0 ? `${h}:${String(m).padStart(2, "0")}:${ss}` : `${m}:${ss}`;
}

/** "1.5 GB" / "1,5 GB": the number uses the UI locale's separators. */
export function formatBytes(bytes: number | null | undefined, locale: Locale = currentLocale()): string {
  if (bytes == null || !Number.isFinite(bytes)) return "";
  const units = ["B", "KB", "MB", "GB", "TB"];
  let v = bytes;
  let i = 0;
  while (v >= 1024 && i < units.length - 1) {
    v /= 1024;
    i++;
  }
  const digits = v < 10 && i > 0 ? 1 : 0;
  const n = formatNumber(v, { minimumFractionDigits: digits, maximumFractionDigits: digits }, locale);
  return `${n} ${units[i]}`;
}

/** "3 minutes ago" / "3 minuti fa" in the current UI language. */
export function formatRelative(iso: string, now: number = Date.now()): string {
  return formatRelativeTime(iso, now);
}

export function hostOf(url: string): string {
  try {
    return new URL(url).host.replace(/^www\./, "");
  } catch {
    return url;
  }
}

export function shortUrl(url: string, max = 60): string {
  let s = url;
  try {
    const u = new URL(url);
    s = `${u.host}${u.pathname}`;
  } catch {
    /* keep raw */
  }
  return s.length > max ? `${s.slice(0, max - 1)}…` : s;
}

/** Dictionary key of each source kind's label (translate with `t(SOURCE_LABEL_KEY[kind])`). */
export const SOURCE_LABEL_KEY: Record<SourceKind, MessageKey> = {
  direct: "source.direct",
  webpage: "source.webpage",
  m3u: "source.m3u",
  ytdlp: "source.ytdlp",
  local: "source.local",
};
