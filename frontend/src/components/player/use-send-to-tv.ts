"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { toast } from "sonner";
import { t } from "@/i18n";
import type { PlayerState } from "@/lib/api/types";
import { onCastEvent } from "@/lib/cast-events";
import { useAppStore, type AppData } from "@/stores/app-store";
import { useUiStore } from "@/stores/ui-store";

/** No PLAYING within this long after the target is known = the cast failed (the player stays open). */
export const SEND_TIMEOUT_MS = 45_000;

export type SendState =
  | { phase: "idle" }
  /** Waiting for the target (the device picker may be open over the player). */
  | { phase: "choosing" }
  /** Casting to `deviceId`, until the receiver plays the media. */
  | { phase: "sending"; deviceId: string };

/** The receiver plays the cast's media (not a stale snapshot of what it played before the cast). */
export function castLanded(player: PlayerState | null | undefined, pending: boolean, answer: PlayerState): boolean {
  if (pending || !player) return false;
  if (player.player_state !== "PLAYING" && player.player_state !== "PAUSED") return false;
  if (player.showing_idle_image || player.recovering) return false;
  if (answer.original_input && player.original_input) return answer.original_input === player.original_input;
  if (answer.media_url && player.media_url) return answer.media_url === player.media_url;
  return true;
}

function deviceName(s: AppData, id: string): string {
  return s.appState?.devices.find((d) => d.id === id)?.name ?? "Chromecast";
}

/**
 * "Send to TV" from the local player without leaving it. `start(cast)` runs the cast and follows it through
 * the cast events (device chosen / request answered / failed / picker dismissed) and then the WebSocket-fed
 * store: `onLanded` runs once that device plays the media (its optimistic pending load is over and the
 * snapshot shows PLAYING or PAUSED). Dismissing the picker goes back to idle; a failed request, a receiver
 * that goes IDLE or no playback within `SEND_TIMEOUT_MS` go back to idle with `error` set.
 */
export function useSendToTv(onLanded: () => void) {
  const [state, setState] = useState<SendState>({ phase: "idle" });
  const [error, setError] = useState<string | null>(null);
  const cleanups = useRef<(() => void)[]>([]);
  const landedRef = useRef(onLanded);
  useEffect(() => {
    landedRef.current = onLanded;
  }, [onLanded]);

  const stop = useCallback(() => {
    for (const fn of cleanups.current.splice(0)) fn();
  }, []);
  useEffect(() => stop, [stop]);

  const start = useCallback(
    (cast: () => void) => {
      stop();
      setError(null);
      setState({ phase: "choosing" });
      let deviceId: string | null = null;
      let timer: ReturnType<typeof setTimeout> | undefined;
      const later = (fn: () => void) => {
        clearTimeout(timer);
        timer = setTimeout(fn, SEND_TIMEOUT_MS);
      };
      cleanups.current.push(() => clearTimeout(timer));

      const finish = (message?: string, notify = false) => {
        stop();
        setState({ phase: "idle" });
        if (message) {
          setError(message);
          if (notify) toast.error(message);
        }
      };
      // `notify`: toast it too, unless the server already toasts the failure (playback_failed on IDLE/ERROR)
      const notStarted = (notify = true) =>
        finish(t("localPlayer.castNotStarted", { device: deviceName(useAppStore.getState(), deviceId ?? "") }), notify);

      // nothing heard yet: give up quietly, but never while the user is still choosing a device
      const waitForTarget = () =>
        later(() => (useUiStore.getState().devicePickerOpen ? waitForTarget() : finish()));
      waitForTarget();

      const watch = (answer: PlayerState) => {
        const check = (s: AppData) => {
          const id = answer.device_id;
          const player = s.appState?.players[id];
          const pending = !!s.pendingLoad[id];
          if (castLanded(player, pending, answer)) {
            finish();
            landedRef.current();
          } else if (!pending && player?.player_state === "IDLE") notStarted(false);
        };
        cleanups.current.push(useAppStore.subscribe(check));
        check(useAppStore.getState());
      };

      cleanups.current.push(
        onCastEvent((e) => {
          if (e.type === "cancel") finish();
          else if (e.type === "device") {
            deviceId = e.deviceId;
            setState({ phase: "sending", deviceId: e.deviceId });
            later(() => notStarted());
          } else if (e.type === "ok") {
            if (deviceId !== e.player.device_id) {
              deviceId = e.player.device_id;
              setState({ phase: "sending", deviceId });
              later(() => notStarted());
            }
            watch(e.player);
          } else finish(e.message); // the cast path already showed a toast
        }),
      );
      cast();
    },
    [stop],
  );

  const name = useAppStore((s) => (state.phase === "sending" ? deviceName(s, state.deviceId) : ""));
  return { state, error, deviceName: name, start };
}
