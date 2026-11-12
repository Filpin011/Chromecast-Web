import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("sonner", () => {
  const toast = Object.assign(vi.fn(), { error: vi.fn(), success: vi.fn(), loading: vi.fn() });
  return { toast };
});

import { toast } from "sonner";
import { handleServerMessage } from "@/components/app/state-socket-bridge";
import {
  initialAppData,
  reducePlayer,
  effectiveReceivedAt,
  reduceSnapshot,
  selectActiveDevice,
  selectDevices,
  selectPlayer,
  useAppStore,
} from "@/stores/app-store";
import { extrapolatePosition } from "@/lib/player";
import { makeAppState, makeDevice, makePlayer } from "./fixtures";

beforeEach(() => useAppStore.getState().reset());

describe("reduceSnapshot", () => {
  it("accepts the first snapshot and records receive time per player", () => {
    const s = reduceSnapshot(initialAppData, makeAppState(), 1000);
    expect(s.appState?.version).toBe(1);
    expect(s.receivedAt["dev-1"]).toBe(1000);
    expect(s.acceptAnyVersion).toBe(false);
  });

  it("ignores stale (older version) snapshots", () => {
    const a = reduceSnapshot(initialAppData, makeAppState({ version: 5 }), 1000);
    const b = reduceSnapshot(a, makeAppState({ version: 4, discovering: true }), 2000);
    expect(b).toBe(a);
  });

  it("accepts any version right after a reconnect (server restart)", () => {
    const a = reduceSnapshot(initialAppData, makeAppState({ version: 50 }), 1000);
    const b = reduceSnapshot({ ...a, acceptAnyVersion: true }, makeAppState({ version: 1 }), 2000);
    expect(b.appState?.version).toBe(1);
  });

  it("keeps receivedAt when the player did not change (no progress jump)", () => {
    const a = reduceSnapshot(initialAppData, makeAppState({ version: 1 }), 1000);
    const b = reduceSnapshot(a, makeAppState({ version: 2, discovering: true }), 5000);
    expect(b.receivedAt["dev-1"]).toBe(1000);
    const moved = makeAppState({ version: 3, players: { "dev-1": makePlayer({ current_time: 20 }) } });
    expect(reduceSnapshot(b, moved, 6000).receivedAt["dev-1"]).toBe(6000);
  });
});

describe("reduceSnapshot structural sharing", () => {
  it("keeps unchanged devices and players identical across freshly parsed snapshots", () => {
    const a = reduceSnapshot(initialAppData, makeAppState({ version: 1 }), 1000);
    // a fresh JSON-parsed snapshot: equal content, new objects
    const fresh = JSON.parse(JSON.stringify(makeAppState({ version: 2 })));
    const b = reduceSnapshot(a, fresh, 2000);
    expect(b.appState?.devices).toBe(a.appState?.devices);
    expect(b.appState?.players["dev-1"]).toBe(a.appState?.players["dev-1"]);
    expect(b.appState?.players).toBe(a.appState?.players);
    expect(b.receivedAt).toBe(a.receivedAt);
  });

  it("replaces only what changed", () => {
    const two = [makeDevice(), makeDevice({ id: "dev-2", name: "Camera" })];
    const a = reduceSnapshot(initialAppData, makeAppState({ devices: two }), 1000);
    const renamed = [makeDevice(), makeDevice({ id: "dev-2", name: "Cucina" })];
    const b = reduceSnapshot(a, JSON.parse(JSON.stringify(makeAppState({ version: 2, devices: renamed }))), 2000);
    expect(b.appState?.devices).not.toBe(a.appState?.devices);
    expect(b.appState?.devices[0]).toBe(a.appState?.devices[0]);
    expect(b.appState?.devices[1].name).toBe("Cucina");
    const moved = makeAppState({ version: 3, devices: renamed, players: { "dev-1": makePlayer({ current_time: 11 }) } });
    const c = reduceSnapshot(b, moved, 3000);
    expect(c.appState?.players["dev-1"].current_time).toBe(11);
    expect(c.appState?.devices).toBe(b.appState?.devices);
  });
});

describe("reducePlayer & optimistic overlays", () => {
  it("optimistic seek restarts the progress clock (no jump past the target)", () => {
    vi.useFakeTimers();
    try {
      vi.setSystemTime(1000);
      const st = useAppStore.getState();
      st.applySnapshot(makeAppState({ players: { "dev-1": makePlayer({ current_time: 10, duration: 600, stream_type: "BUFFERED" }) } }));
      vi.setSystemTime(1900);
      st.pushOptimistic("dev-1", { current_time: 300 });
      const s = useAppStore.getState();
      const p = selectPlayer(s, "dev-1");
      const since = effectiveReceivedAt(s.receivedAt["dev-1"], s.optimistic["dev-1"]);
      expect(since).toBe(1900);
      expect(extrapolatePosition(p, since, 1900)).toBe(300);
      // non-seek overlays do not touch the clock
      expect(effectiveReceivedAt(1000, [{ id: 1, patch: { muted: true }, at: 5000 }])).toBe(1000);
    } finally {
      vi.useRealTimers();
    }
  });

  it("merges a REST PlayerState into the snapshot", () => {
    const a = reduceSnapshot(initialAppData, makeAppState(), 1000);
    const b = reducePlayer(a, makePlayer({ player_state: "PAUSED" }), 2000);
    expect(b.appState?.players["dev-1"].player_state).toBe("PAUSED");
    expect(b.receivedAt["dev-1"]).toBe(2000);
    expect(reducePlayer(initialAppData, makePlayer(), 1)).toBe(initialAppData);
  });

  it("applies and reverts optimistic patches on read", () => {
    const st = useAppStore.getState();
    st.applySnapshot(makeAppState());
    const revert = st.pushOptimistic("dev-1", { muted: true });
    const revert2 = useAppStore.getState().pushOptimistic("dev-1", { volume_level: 0.9 });
    let p = selectPlayer(useAppStore.getState(), "dev-1");
    expect(p?.muted).toBe(true);
    expect(p?.volume_level).toBe(0.9);
    revert();
    p = selectPlayer(useAppStore.getState(), "dev-1");
    expect(p?.muted).toBe(false);
    expect(p?.volume_level).toBe(0.9);
    revert2();
    expect(useAppStore.getState().optimistic).toEqual({});
  });

  it("re-accepts any version after the socket reopens", () => {
    const st = useAppStore.getState();
    st.applySnapshot(makeAppState({ version: 10 }));
    st.setConnection("open");
    useAppStore.getState().applySnapshot(makeAppState({ version: 2 }));
    expect(useAppStore.getState().appState?.version).toBe(2);
  });
});

describe("selectors", () => {
  it("select devices, active device and player", () => {
    useAppStore.getState().applySnapshot(makeAppState());
    const s = useAppStore.getState();
    expect(selectDevices(s)).toHaveLength(1);
    expect(selectActiveDevice(s)?.name).toBe("Salotto");
    expect(selectPlayer(s, "nope")).toBeNull();
    expect(selectPlayer(s, null)).toBeNull();
    useAppStore.getState().setActiveDevice(null);
    expect(selectActiveDevice(useAppStore.getState())).toBeNull();
  });
});

describe("handleServerMessage", () => {
  it("feeds state snapshots into the store", () => {
    handleServerMessage({ type: "state", data: makeAppState({ version: 7 }) });
    expect(useAppStore.getState().appState?.version).toBe(7);
  });
  it("routes toasts by level", () => {
    handleServerMessage({ type: "toast", level: "error", message: "boom" });
    handleServerMessage({ type: "toast", level: "success", message: "ok" });
    handleServerMessage({ type: "toast", level: "info", message: "fyi" });
    handleServerMessage({ type: "pong" });
    expect(toast.error).toHaveBeenCalledWith("boom");
    expect(toast.success).toHaveBeenCalledWith("ok");
    expect(toast).toHaveBeenCalledWith("fyi");
  });
});
