/**
 * Progress of a cast this client starts, for whoever waits on its outcome (the "Watch here" player stays
 * open until the Chromecast plays). `useCast` emits these for every play (not for enqueues); other cast
 * paths that bypass it (e.g. resuming the TV from the local player) emit them too.
 */
import type { PlayerState } from "@/lib/api/types";

export type CastEvent =
  /** The device picker was dismissed: nothing was cast. */
  | { type: "cancel" }
  /** The target is known; the play request goes out now. */
  | { type: "device"; deviceId: string }
  /** The play request answered (the receiver may still be loading). */
  | { type: "ok"; player: PlayerState }
  /** The play request failed (the caller already showed a toast). */
  | { type: "error"; message: string };

type Listener = (e: CastEvent) => void;

const listeners = new Set<Listener>();

/** Returns the unsubscribe function. */
export function onCastEvent(fn: Listener): () => void {
  listeners.add(fn);
  return () => {
    listeners.delete(fn);
  };
}

export function emitCastEvent(e: CastEvent) {
  for (const fn of [...listeners]) fn(e);
}
