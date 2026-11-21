"use client";

import { usePendingLoad } from "@/hooks/use-app-state";
import type { PlayerState } from "@/lib/api/types";
import type { Translator } from "@/i18n";
import { loadingStatus, type LoadingStatus } from "@/lib/player";

/** Loading indicator state of a device's player, including this client's optimistic "cast just started". */
export function useLoadingStatus(deviceId: string | null | undefined, player: PlayerState | null): LoadingStatus | null {
  const pending = usePendingLoad(deviceId);
  return loadingStatus(player, pending);
}

/** Status line text for a loading state. */
export function loadingLabel(status: LoadingStatus, t: Translator): string {
  switch (status.kind) {
    case "recovering":
      return t("player.reconnecting", { attempt: status.attempt, max: status.max });
    case "stalled":
      return t("player.stalled");
    default:
      return t("player.loading");
  }
}

/** Status line color: a struggling stream stands out (amber), a plain load stays muted. */
export function loadingTone(status: LoadingStatus | null): string {
  return status && status.kind !== "loading" ? "text-amber-600 dark:text-amber-400" : "text-muted-foreground";
}
