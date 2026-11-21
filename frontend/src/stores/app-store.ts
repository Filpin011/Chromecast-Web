import { create } from "zustand";
import type { AppState, Device, PlayerState } from "@/lib/api/types";
import type { SocketStatus } from "@/lib/ws/reconnecting-socket";

export interface OptimisticPatch {
  id: number;
  patch: Partial<PlayerState>;
  /** Client clock (ms) when the overlay was pushed: a patched `current_time` is extrapolated from here. */
  at: number;
}

export interface AppData {
  appState: AppState | null;
  connection: SocketStatus;
  /** Client clock (ms) when each player's snapshot was received — used for progress extrapolation. */
  receivedAt: Record<string, number>;
  /** Pending optimistic overlays per device, applied on read until the command settles. */
  optimistic: Record<string, OptimisticPatch[]>;
  /** When true, the next snapshot is accepted regardless of version (server restart/reconnect). */
  acceptAnyVersion: boolean;
  /** Casts this client started whose media has not reached PLAYING yet (optimistic loading indicator). */
  pendingLoad: Record<string, PendingLoad>;
}

export interface PendingLoad {
  /** Client clock (ms) when the cast was requested. */
  since: number;
  /** The play request answered: the next snapshot that shows playback (or IDLE) ends the wait. */
  settled: boolean;
}

/** A pending load never outlives this (the indicator must not spin forever if a snapshot is missed). */
export const PENDING_LOAD_MAX_MS = 90_000;

export const initialAppData: AppData = {
  appState: null,
  connection: "idle",
  receivedAt: {},
  optimistic: {},
  acceptAnyVersion: true,
  pendingLoad: {},
};

/* ------------------------------------------------------------------ */
/* Pure reducers (unit-tested)                                         */
/* ------------------------------------------------------------------ */

function playerChanged(a: PlayerState | undefined, b: PlayerState): boolean {
  return !a || a.updated_at !== b.updated_at || a.current_time !== b.current_time || a.player_state !== b.player_state;
}

/** Structural equality for JSON-shaped values (snapshots are plain parsed JSON). */
export function jsonEqual(a: unknown, b: unknown): boolean {
  if (a === b) return true;
  if (typeof a !== "object" || typeof b !== "object" || a === null || b === null) return false;
  if (Array.isArray(a) !== Array.isArray(b)) return false;
  if (Array.isArray(a)) {
    const bb = b as unknown[];
    return a.length === bb.length && a.every((v, i) => jsonEqual(v, bb[i]));
  }
  const ka = Object.keys(a);
  const kb = Object.keys(b);
  if (ka.length !== kb.length) return false;
  return ka.every((k) => Object.prototype.hasOwnProperty.call(b, k) && jsonEqual((a as Record<string, unknown>)[k], (b as Record<string, unknown>)[k]));
}

/** Reuse previous objects that did not change so subscribers relying on identity don't re-render every tick. */
function shareDevices(prev: Device[] | undefined, next: Device[]): Device[] {
  if (!prev) return next;
  const byId = new Map(prev.map((d) => [d.id, d]));
  let same = prev.length === next.length;
  const out = next.map((d, i) => {
    const old = byId.get(d.id);
    const keep = old && jsonEqual(old, d) ? old : d;
    if (keep !== prev[i]) same = false;
    return keep;
  });
  return same ? prev : out;
}

function sharePlayers(prev: Record<string, PlayerState> | undefined, next: Record<string, PlayerState>): Record<string, PlayerState> {
  if (!prev) return next;
  const out: Record<string, PlayerState> = {};
  let same = Object.keys(prev).length === Object.keys(next).length;
  for (const [id, p] of Object.entries(next)) {
    const old = prev[id];
    out[id] = old && jsonEqual(old, p) ? old : p;
    if (out[id] !== old) same = false;
  }
  return same ? prev : out;
}

export function reduceSnapshot(prev: AppData, next: AppState, now: number): AppData {
  const cur = prev.appState;
  if (cur && !prev.acceptAnyVersion && next.version < cur.version) return prev;
  const receivedAt: Record<string, number> = {};
  for (const [id, p] of Object.entries(next.players)) {
    const old = cur?.players[id];
    receivedAt[id] = playerChanged(old, p) ? now : (prev.receivedAt[id] ?? now);
  }
  const appState: AppState = {
    ...next,
    devices: shareDevices(cur?.devices, next.devices),
    players: sharePlayers(cur?.players, next.players),
  };
  const sameReceived = jsonEqual(prev.receivedAt, receivedAt);
  return {
    ...prev,
    appState,
    receivedAt: sameReceived ? prev.receivedAt : receivedAt,
    acceptAnyVersion: false,
    pendingLoad: prunePendingLoad(prev.pendingLoad, next.players, now),
  };
}

/** The cast's media has started (or ended): the optimistic loading indicator can go. */
function loadSettled(p: PlayerState | undefined): boolean {
  if (!p) return true;
  if (p.recovering || p.player_state === "BUFFERING") return false;
  return (
    p.player_state === "IDLE" || ((p.player_state === "PLAYING" || p.player_state === "PAUSED") && !p.showing_idle_image)
  );
}

function prunePendingLoad(
  pending: Record<string, PendingLoad>,
  players: Record<string, PlayerState>,
  now: number,
): Record<string, PendingLoad> {
  const ids = Object.keys(pending);
  if (!ids.length) return pending;
  const out: Record<string, PendingLoad> = {};
  for (const id of ids) {
    const e = pending[id];
    if (now - e.since > PENDING_LOAD_MAX_MS || (e.settled && loadSettled(players[id]))) continue;
    out[id] = e;
  }
  return Object.keys(out).length === ids.length ? pending : out;
}

export function reduceStartPendingLoad(prev: AppData, deviceId: string, now: number): AppData {
  return { ...prev, pendingLoad: { ...prev.pendingLoad, [deviceId]: { since: now, settled: false } } };
}

/** The play request answered with `player`: wait for the first snapshot showing playback, unless it already does. */
export function reduceSettlePendingLoad(prev: AppData, deviceId: string, player: PlayerState | null): AppData {
  const e = prev.pendingLoad[deviceId];
  if (!e) return prev;
  if (player && player.player_state !== "IDLE" && loadSettled(player)) return reduceClearPendingLoad(prev, deviceId);
  return { ...prev, pendingLoad: { ...prev.pendingLoad, [deviceId]: { ...e, settled: true } } };
}

export function reduceClearPendingLoad(prev: AppData, deviceId: string): AppData {
  if (!prev.pendingLoad[deviceId]) return prev;
  const pendingLoad = { ...prev.pendingLoad };
  delete pendingLoad[deviceId];
  return { ...prev, pendingLoad };
}

/** Merge a PlayerState returned by a REST command into the current snapshot. */
export function reducePlayer(prev: AppData, player: PlayerState, now: number): AppData {
  const cur = prev.appState;
  if (!cur) return prev;
  return {
    ...prev,
    appState: { ...cur, players: { ...cur.players, [player.device_id]: player } },
    receivedAt: { ...prev.receivedAt, [player.device_id]: now },
  };
}

export function reduceActiveDevice(prev: AppData, deviceId: string | null): AppData {
  if (!prev.appState) return prev;
  return { ...prev, appState: { ...prev.appState, active_device_id: deviceId } };
}

export function addOptimistic(prev: AppData, deviceId: string, entry: OptimisticPatch): AppData {
  const list = prev.optimistic[deviceId] ?? [];
  return { ...prev, optimistic: { ...prev.optimistic, [deviceId]: [...list, entry] } };
}

export function removeOptimistic(prev: AppData, deviceId: string, id: number): AppData {
  const list = (prev.optimistic[deviceId] ?? []).filter((e) => e.id !== id);
  const optimistic = { ...prev.optimistic };
  if (list.length) optimistic[deviceId] = list;
  else delete optimistic[deviceId];
  return { ...prev, optimistic };
}

export function applyOverlays(player: PlayerState, overlays: OptimisticPatch[] | undefined): PlayerState {
  if (!overlays?.length) return player;
  return overlays.reduce<PlayerState>((p, o) => ({ ...p, ...o.patch }), player);
}

/* ------------------------------------------------------------------ */
/* Store                                                               */
/* ------------------------------------------------------------------ */

export interface AppActions {
  applySnapshot: (s: AppState) => void;
  applyPlayer: (p: PlayerState) => void;
  setActiveDevice: (id: string | null) => void;
  setConnection: (s: SocketStatus) => void;
  /** Returns a revert function. */
  pushOptimistic: (deviceId: string, patch: Partial<PlayerState>) => () => void;
  startPendingLoad: (deviceId: string) => void;
  settlePendingLoad: (deviceId: string, player: PlayerState | null) => void;
  clearPendingLoad: (deviceId: string) => void;
  reset: () => void;
}

export type AppStore = AppData & AppActions;

let optimisticSeq = 0;

export const useAppStore = create<AppStore>()((set) => ({
  ...initialAppData,
  applySnapshot: (s) => set((prev) => reduceSnapshot(prev, s, Date.now())),
  applyPlayer: (p) => set((prev) => reducePlayer(prev, p, Date.now())),
  setActiveDevice: (id) => set((prev) => reduceActiveDevice(prev, id)),
  setConnection: (connection) =>
    set((prev) => ({
      connection,
      // after a (re)connect accept whatever the server sends first (it may have restarted)
      acceptAnyVersion: connection === "open" ? true : prev.acceptAnyVersion,
    })),
  pushOptimistic: (deviceId, patch) => {
    const id = ++optimisticSeq;
    set((prev) => addOptimistic(prev, deviceId, { id, patch, at: Date.now() }));
    return () => set((prev) => removeOptimistic(prev, deviceId, id));
  },
  startPendingLoad: (deviceId) => set((prev) => reduceStartPendingLoad(prev, deviceId, Date.now())),
  settlePendingLoad: (deviceId, player) => set((prev) => reduceSettlePendingLoad(prev, deviceId, player)),
  clearPendingLoad: (deviceId) => set((prev) => reduceClearPendingLoad(prev, deviceId)),
  reset: () => set({ ...initialAppData }),
}));

export function selectPendingLoad(s: AppData, deviceId: string | null | undefined): boolean {
  return !!deviceId && !!s.pendingLoad[deviceId];
}

/* ------------------------------------------------------------------ */
/* Selectors                                                           */
/* ------------------------------------------------------------------ */

export function selectDevices(s: AppData): Device[] {
  return s.appState?.devices ?? [];
}

export function selectActiveDevice(s: AppData): Device | null {
  const st = s.appState;
  if (!st?.active_device_id) return null;
  return st.devices.find((d) => d.id === st.active_device_id) ?? null;
}

/**
 * Clock to extrapolate playback progress from: an overlay that moved `current_time` (optimistic seek)
 * restarts the clock at the moment it was pushed, so the bar doesn't jump past the target.
 */
export function effectiveReceivedAt(receivedAt: number, overlays: OptimisticPatch[] | undefined): number {
  let t = receivedAt;
  for (const o of overlays ?? []) if (o.patch.current_time !== undefined && o.at > t) t = o.at;
  return t;
}

export function selectPlayer(s: AppData, deviceId: string | null | undefined): PlayerState | null {
  if (!deviceId) return null;
  const p = s.appState?.players[deviceId];
  return p ? applyOverlays(p, s.optimistic[deviceId]) : null;
}
