import type { ControlAction, PlayerState } from "@/lib/api/types";

/** Playback position extrapolated from the last snapshot. */
export function extrapolatePosition(p: PlayerState | null, receivedAt: number, now: number): number {
  if (!p) return 0;
  let t = p.current_time;
  if (p.player_state === "PLAYING" && receivedAt > 0) t += Math.max(0, now - receivedAt) / 1000;
  if (p.duration != null && p.duration > 0) t = Math.min(t, p.duration);
  return Math.max(0, t);
}

export function isLive(p: Pick<PlayerState, "stream_type" | "duration"> | null): boolean {
  return !!p && (p.stream_type === "LIVE" || p.duration == null);
}

/**
 * Optimistic patch that a control command is expected to produce.
 * `position` is the playback position the user currently sees (extrapolated), used by relative seeks.
 */
export function optimisticPatch(
  p: PlayerState,
  action: ControlAction,
  value?: number,
  position: number = p.current_time,
): Partial<PlayerState> | null {
  switch (action) {
    case "play":
      return { player_state: "PLAYING" };
    case "pause":
      return { player_state: "PAUSED" };
    case "toggle":
      return { player_state: p.player_state === "PLAYING" ? "PAUSED" : "PLAYING" };
    case "stop":
      return { player_state: "IDLE" };
    case "mute":
      return { muted: true };
    case "unmute":
      return { muted: false };
    case "volume":
      return value === undefined ? null : { volume_level: clamp01(value), muted: false };
    case "volume_relative":
      return value === undefined ? null : { volume_level: clamp01(p.volume_level + value) };
    case "seek":
      return value === undefined ? null : { current_time: Math.max(0, value) };
    case "seek_relative":
      return value === undefined ? null : { current_time: Math.max(0, position + value) };
    default:
      return null;
  }
}

function clamp01(v: number): number {
  return Math.min(1, Math.max(0, v));
}
