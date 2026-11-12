"use client";

import { useMemo } from "react";
import { useShallow } from "zustand/react/shallow";
import type { Device, PlayerState } from "@/lib/api/types";
import {
  applyOverlays,
  effectiveReceivedAt,
  selectActiveDevice,
  selectDevices,
  useAppStore,
  type AppStore,
} from "@/stores/app-store";

/** Subscribe to a slice of the live app state (fed by the `/ws` snapshots). */
export function useAppState<T>(selector: (s: AppStore) => T): T {
  return useAppStore(selector);
}

export function useConnection() {
  return useAppStore((s) => s.connection);
}

export function useHasSnapshot() {
  return useAppStore((s) => s.appState !== null);
}

export function useDevices(): Device[] {
  // reduceSnapshot keeps unchanged Device objects (and the array itself) across snapshots
  return useAppStore(useShallow(selectDevices));
}

export function useDiscovering(): boolean {
  return useAppStore((s) => s.appState?.discovering ?? false);
}

export function useActiveDevice(): Device | null {
  return useAppStore(selectActiveDevice);
}

export interface ActivePlayer {
  device: Device | null;
  player: PlayerState | null;
  /** Client clock (ms) at which `player` was received, for progress extrapolation. */
  receivedAt: number;
}

/** The active device and its (optimistically patched) player state. */
export function useActivePlayer(): ActivePlayer {
  // Select only referentially-stable pieces, then apply overlays in a memo
  // (building a new object inside the selector would re-render forever).
  const { device, raw, overlays, receivedAt } = useAppStore(
    useShallow((s) => {
      const device = selectActiveDevice(s);
      return {
        device,
        raw: device ? (s.appState?.players[device.id] ?? null) : null,
        overlays: device ? s.optimistic[device.id] : undefined,
        receivedAt: device ? (s.receivedAt[device.id] ?? 0) : 0,
      };
    }),
  );
  const player = useMemo(() => (raw ? applyOverlays(raw, overlays) : null), [raw, overlays]);
  return { device, player, receivedAt: effectiveReceivedAt(receivedAt, overlays) };
}

export interface ActiveStatus {
  device: Device | null;
  connected: boolean;
  playing: boolean;
}

/**
 * Active device + connection/playback flags only. Unlike `useActivePlayer` it does not change on every
 * progress tick, so headers, device buttons and lists using it don't re-render each second.
 */
export function useActiveStatus(): ActiveStatus {
  return useAppStore(
    useShallow((s) => {
      const device = selectActiveDevice(s);
      const p = device ? (s.appState?.players[device.id] ?? null) : null;
      const player = p && device ? applyOverlays(p, s.optimistic[device.id]) : null;
      return { device, connected: !!player?.connected, playing: isActivePlayback(player) };
    }),
  );
}

export function isActivePlayback(p: PlayerState | null | undefined): boolean {
  // The idle image is itself "PLAYING" on the receiver: it is not user playback (mirrors the backend).
  return (
    !!p && p.connected && !p.showing_idle_image && p.player_state !== "IDLE" && p.player_state !== "UNKNOWN"
  );
}
