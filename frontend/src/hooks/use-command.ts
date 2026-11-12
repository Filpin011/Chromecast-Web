"use client";

import { useCallback, useState } from "react";
import { toast } from "sonner";
import { api } from "@/lib/api";
import type { ControlAction, PlayerState } from "@/lib/api/types";
import { haptic } from "@/lib/haptics";
import { extrapolatePosition, optimisticPatch } from "@/lib/player";
import { errorMessage } from "@/lib/query";
import { effectiveReceivedAt, selectPlayer, useAppStore } from "@/stores/app-store";

export interface CommandRunner {
  run: (action: ControlAction, value?: number) => Promise<PlayerState | null>;
  pending: ControlAction | null;
}

/**
 * Player control commands for a device with optimistic feedback:
 * the expected change is overlaid immediately and replaced by the server's answer
 * (or reverted, with an error toast, if the command fails).
 */
export function useCommand(deviceId: string | null | undefined): CommandRunner {
  const [pending, setPending] = useState<ControlAction | null>(null);

  const run = useCallback(
    async (action: ControlAction, value?: number) => {
      if (!deviceId) {
        toast.error("Nessun dispositivo connesso");
        return null;
      }
      haptic();
      const store = useAppStore.getState();
      const current = selectPlayer(store, deviceId);
      const now = Date.now();
      const since = effectiveReceivedAt(store.receivedAt[deviceId] ?? 0, store.optimistic[deviceId]);
      const patch = current ? optimisticPatch(current, action, value, extrapolatePosition(current, since, now)) : null;
      const revert = patch ? store.pushOptimistic(deviceId, patch) : () => {};
      setPending(action);
      try {
        const res = await api.player.control(deviceId, action, value);
        if (res) useAppStore.getState().applyPlayer(res);
        return res;
      } catch (err) {
        toast.error(errorMessage(err, "Comando non riuscito"));
        return null;
      } finally {
        revert();
        setPending(null);
      }
    },
    [deviceId],
  );

  return { run, pending };
}
