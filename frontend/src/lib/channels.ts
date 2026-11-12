import type { Channel } from "@/lib/api/types";

export type ChannelLayout = "grid" | "list";

/**
 * The channel as a single input string: the URL with its upstream headers folded in using the Kodi
 * syntax `url|Referer=<urlencoded>&User-Agent=<urlencoded>` (see ARCHITECTURE "headers"). This is the
 * form favorites/history store and `/api/resolve` accepts, so the headers survive a later replay.
 */
export function channelInput(c: Pick<Channel, "url" | "headers">): string {
  const entries = Object.entries(c.headers ?? {}).filter(([k, v]) => k && v);
  if (!entries.length) return c.url;
  return `${c.url}|${entries.map(([k, v]) => `${k}=${encodeURIComponent(v)}`).join("&")}`;
}

/**
 * Default layout when the user has not picked one: the logo grid only helps when most channels have
 * logos; otherwise every tile is the same TV icon plus a clipped name, so the list (full names + group)
 * is the readable choice.
 */
export function preferredChannelLayout(sample: readonly Pick<Channel, "logo">[]): ChannelLayout {
  if (!sample.length) return "list";
  const withLogo = sample.filter((c) => !!c.logo).length;
  return withLogo / sample.length >= 0.6 ? "grid" : "list";
}
