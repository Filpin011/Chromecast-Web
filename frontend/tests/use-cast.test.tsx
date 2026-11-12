import { act, renderHook, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("sonner", () => {
  const toast = Object.assign(vi.fn(), { error: vi.fn(), success: vi.fn(), loading: vi.fn().mockReturnValue("t1") });
  return { toast };
});

import { toast } from "sonner";
import { channelRequest, ensureDevice, useCast } from "@/hooks/use-cast";
import { api } from "@/lib/api";
import { useAppStore } from "@/stores/app-store";
import { useUiStore } from "@/stores/ui-store";
import { makeAppState, makePlayer } from "./fixtures";

const wrapper = ({ children }: { children: ReactNode }) => (
  <QueryClientProvider client={new QueryClient()}>{children}</QueryClientProvider>
);

beforeEach(() => {
  useAppStore.getState().reset();
  useUiStore.setState({ devicePickerOpen: false, pendingDevice: null });
});

describe("ensureDevice", () => {
  it("uses the connected active device", async () => {
    useAppStore.getState().applySnapshot(makeAppState());
    await expect(ensureDevice(undefined)).resolves.toBe("dev-1");
  });

  it("targets the default device from settings without connecting first (the cast auto-connects)", async () => {
    useAppStore.getState().applySnapshot(makeAppState({ active_device_id: null, players: {} }));
    const connect = vi.spyOn(api.devices, "connect").mockResolvedValue(makePlayer());
    const id = await ensureDevice({
      default_device_id: "dev-1",
      idle_image_url: null,
      show_idle_on_connect: true,
      show_idle_on_stop: false,
      public_base_url: null,
      force_proxy: false,
      adblock_enabled: true,
      adblock_disabled_hosts: [],
      popup_policy: "ask",
      popup_blocked_hosts: [],
    });
    expect(id).toBe("dev-1");
    // an explicit connect would LOAD the idle image right before the media
    expect(connect).not.toHaveBeenCalled();
    expect(useAppStore.getState().appState?.active_device_id).toBe("dev-1");
  });

  it("reuses the active device while it is (re)connecting, without an explicit connect", async () => {
    useAppStore.getState().applySnapshot(makeAppState({ players: {} }));
    const connect = vi.spyOn(api.devices, "connect");
    await expect(ensureDevice(undefined)).resolves.toBe("dev-1");
    expect(connect).not.toHaveBeenCalled();
    expect(useUiStore.getState().devicePickerOpen).toBe(false);
  });

  it("asks the user via the device sheet otherwise", async () => {
    useAppStore.getState().applySnapshot(makeAppState({ active_device_id: null, players: {} }));
    const p = ensureDevice(undefined);
    await waitFor(() => expect(useUiStore.getState().devicePickerOpen).toBe(true));
    useUiStore.getState().resolveDevice("dev-1");
    await expect(p).resolves.toBe("dev-1");
  });
});

describe("useCast", () => {
  it("plays on the active device and toasts success", async () => {
    useAppStore.getState().applySnapshot(makeAppState());
    const play = vi.spyOn(api.player, "play").mockResolvedValue(makePlayer({ title: "Film" }));
    const { result } = renderHook(() => useCast(), { wrapper });
    await act(() => result.current.cast({ input: "http://a/b.mp4", title: "Film" }));
    expect(play).toHaveBeenCalledWith("dev-1", { input: "http://a/b.mp4", kind: undefined, title: "Film", enqueue: false });
    expect(toast.success).toHaveBeenCalledWith("In riproduzione su Salotto", expect.objectContaining({ id: "t1" }));
  });

  it("enqueues through the queue endpoint", async () => {
    useAppStore.getState().applySnapshot(makeAppState());
    const enqueue = vi.spyOn(api.player, "enqueue").mockResolvedValue(makePlayer());
    const { result } = renderHook(() => useCast(), { wrapper });
    await act(() => result.current.cast({ input: "x", enqueue: true }));
    expect(enqueue).toHaveBeenCalledWith("dev-1", { input: "x", kind: undefined, title: undefined });
  });

  it("casts captured browser streams with the enqueue flag", async () => {
    useAppStore.getState().applySnapshot(makeAppState());
    const cast = vi.spyOn(api.browser, "cast").mockResolvedValue(makePlayer());
    const { result } = renderHook(() => useCast(), { wrapper });
    await act(() => result.current.castCaptured("b1", "s1", { enqueue: true }));
    expect(cast).toHaveBeenCalledWith("b1", { stream_id: "s1", device_id: "dev-1", enqueue: true });
  });

  it("plays straight away on a known but disconnected device: no connect call before play", async () => {
    useAppStore.getState().applySnapshot(makeAppState({ players: {} }));
    const calls: string[] = [];
    vi.spyOn(api.devices, "connect").mockImplementation(async () => {
      calls.push("connect");
      return makePlayer();
    });
    vi.spyOn(api.player, "play").mockImplementation(async () => {
      calls.push("play");
      return makePlayer();
    });
    const { result } = renderHook(() => useCast(), { wrapper });
    await act(() => result.current.cast({ input: "http://a/b.mp4" }));
    expect(calls).toEqual(["play"]);
  });

  it("does nothing when the user dismisses the device sheet", async () => {
    useAppStore.getState().applySnapshot(makeAppState({ active_device_id: null, players: {} }));
    const play = vi.spyOn(api.player, "play");
    const { result } = renderHook(() => useCast(), { wrapper });
    let done: Promise<unknown> = Promise.resolve();
    act(() => {
      done = result.current.cast({ input: "x" });
    });
    await waitFor(() => expect(useUiStore.getState().devicePickerOpen).toBe(true));
    act(() => useUiStore.getState().setDevicePickerOpen(false));
    await expect(done).resolves.toBeNull();
    expect(play).not.toHaveBeenCalled();
  });

  it("reports failures", async () => {
    useAppStore.getState().applySnapshot(makeAppState());
    vi.spyOn(api.player, "play").mockRejectedValue(new Error("resolve_failed"));
    const { result } = renderHook(() => useCast(), { wrapper });
    await act(() => result.current.cast({ input: "x" }));
    expect(toast.error).toHaveBeenCalledWith("resolve_failed", expect.objectContaining({ id: "t1" }));
  });
});

describe("casting an IPTV channel", () => {
  const channel = {
    url: "http://iptv.example/ch1.m3u8",
    name: "Canale 1",
    headers: { Referer: "http://iptv.example/", "User-Agent": "VLC/3.0" },
  };

  it("sends the playlist's per-channel headers with play and queue", async () => {
    useAppStore.getState().applySnapshot(makeAppState());
    const play = vi.spyOn(api.player, "play").mockResolvedValue(makePlayer());
    const enqueue = vi.spyOn(api.player, "enqueue").mockResolvedValue(makePlayer());
    const { result } = renderHook(() => useCast(), { wrapper });
    await act(() => result.current.cast(channelRequest(channel)));
    expect(play).toHaveBeenCalledWith("dev-1", {
      input: channel.url,
      title: "Canale 1",
      headers: channel.headers,
      enqueue: false,
    });
    await act(() => result.current.cast(channelRequest(channel, true)));
    expect(enqueue).toHaveBeenCalledWith("dev-1", { input: channel.url, title: "Canale 1", headers: channel.headers });
  });

  it("omits headers when the channel has none", () => {
    expect(channelRequest({ url: "u", name: "n", headers: {} })).toEqual({ input: "u", title: "n" });
    expect(channelRequest({ url: "u", name: "n" })).toEqual({ input: "u", title: "n" });
  });
});
