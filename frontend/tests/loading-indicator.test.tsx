import { act, renderHook, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("sonner", () => {
  const toast = Object.assign(vi.fn(), { error: vi.fn(), success: vi.fn(), loading: vi.fn().mockReturnValue("t1") });
  return { toast };
});

import { selectHasMiniPlayer } from "@/components/app/app-shell";
import { toastText } from "@/components/app/state-socket-bridge";
import { MiniPlayer } from "@/components/player/mini-player";
import { NowPlayingContent } from "@/components/player/now-playing";
import { isActivePlayback } from "@/hooks/use-app-state";
import { useCast } from "@/hooks/use-cast";
import { useLocaleStore } from "@/i18n";
import { api } from "@/lib/api";
import type { PlayerState } from "@/lib/api/types";
import { loadingStatus } from "@/lib/player";
import {
  initialAppData,
  PENDING_LOAD_MAX_MS,
  reduceClearPendingLoad,
  reduceSettlePendingLoad,
  reduceSnapshot,
  reduceStartPendingLoad,
  useAppStore,
} from "@/stores/app-store";
import { useUiStore } from "@/stores/ui-store";
import { makeAppState, makeDevice, makePlayer } from "./fixtures";
import { renderWithProviders } from "./render";

const STALLED = "2026-11-12T10:00:05Z";

function setPlayer(over: Partial<PlayerState>) {
  useAppStore.getState().applySnapshot(makeAppState({ players: { "dev-1": makePlayer(over) }, version: Date.now() }));
}

function renderNowPlaying(over: Partial<PlayerState> = {}) {
  setPlayer(over);
  const player = useAppStore.getState().appState!.players["dev-1"];
  return renderWithProviders(<NowPlayingContent device={makeDevice()} player={player} receivedAt={0} />);
}

beforeEach(() => {
  useAppStore.getState().reset();
  useUiStore.setState({ nowPlayingOpen: false, devicePickerOpen: false });
  useLocaleStore.setState({ locale: "en", hydrated: true });
});

afterEach(() => {
  useLocaleStore.setState({ locale: "en", hydrated: true });
});

describe("loadingStatus", () => {
  it("ranks recovering over stalled over loading", () => {
    expect(loadingStatus(makePlayer())).toBeNull();
    expect(loadingStatus(makePlayer({ player_state: "BUFFERING" }))).toEqual({ kind: "loading" });
    expect(loadingStatus(makePlayer({ player_state: "BUFFERING", stalled_since: STALLED }))).toEqual({ kind: "stalled" });
    expect(
      loadingStatus(makePlayer({ player_state: "IDLE", recovering: true, recovery_attempt: 2, stalled_since: STALLED })),
    ).toEqual({ kind: "recovering", attempt: 2, max: 3 });
  });

  it("shows the optimistic load until PLAYING, and nothing for the idle image or a disconnected player", () => {
    expect(loadingStatus(makePlayer({ player_state: "IDLE" }), true)).toEqual({ kind: "loading" });
    expect(loadingStatus(null, true)).toEqual({ kind: "loading" });
    expect(loadingStatus(null)).toBeNull();
    expect(loadingStatus(makePlayer({ player_state: "BUFFERING", showing_idle_image: true }))).toBeNull();
    expect(loadingStatus(makePlayer({ connected: false, player_state: "BUFFERING" }))).toBeNull();
  });

  it("treats a stream being recovered as active playback", () => {
    expect(isActivePlayback(makePlayer({ player_state: "IDLE" }))).toBe(false);
    expect(isActivePlayback(makePlayer({ player_state: "IDLE", recovering: true, recovery_attempt: 1 }))).toBe(true);
  });
});

describe("pending load reducers", () => {
  const snap = (p: PlayerState) => makeAppState({ players: { "dev-1": p }, version: 2 });

  it("waits for the first PLAYING after the request answered", () => {
    let s = reduceSnapshot(initialAppData, snap(makePlayer({ player_state: "IDLE" })), 0);
    s = reduceStartPendingLoad(s, "dev-1", 0);
    // snapshots during the request (old media PLAYING, receiver launching) don't end it
    s = reduceSnapshot(s, snap(makePlayer({ player_state: "PLAYING" })), 10);
    expect(s.pendingLoad["dev-1"]).toBeTruthy();
    s = reduceSettlePendingLoad(s, "dev-1", makePlayer({ player_state: "BUFFERING" }));
    expect(s.pendingLoad["dev-1"]).toEqual({ since: 0, settled: true });
    s = reduceSnapshot(s, snap(makePlayer({ player_state: "BUFFERING" })), 20);
    expect(s.pendingLoad["dev-1"]).toBeTruthy();
    s = reduceSnapshot(s, snap(makePlayer({ player_state: "PLAYING" })), 30);
    expect(s.pendingLoad).toEqual({});
  });

  it("ends right away when the answer already plays, on errors and after the timeout", () => {
    const start = reduceStartPendingLoad(reduceSnapshot(initialAppData, snap(makePlayer()), 0), "dev-1", 0);
    expect(reduceSettlePendingLoad(start, "dev-1", makePlayer({ player_state: "PLAYING" })).pendingLoad).toEqual({});
    expect(reduceClearPendingLoad(start, "dev-1").pendingLoad).toEqual({});
    const late = reduceSnapshot(start, snap(makePlayer({ player_state: "BUFFERING" })), PENDING_LOAD_MAX_MS + 1);
    expect(late.pendingLoad).toEqual({});
  });

  it("keeps the mini player up while a cast is starting on an idle device", () => {
    let s = reduceSnapshot(initialAppData, snap(makePlayer({ player_state: "IDLE" })), 0);
    expect(selectHasMiniPlayer(s)).toBe(false);
    s = reduceStartPendingLoad(s, "dev-1", 0);
    expect(selectHasMiniPlayer(s)).toBe(true);
  });
});

describe("NowPlayingContent loading indicator", () => {
  it("shows Loading… with a spinner over the artwork while buffering", () => {
    renderNowPlaying({ player_state: "BUFFERING" });
    expect(screen.getByRole("status")).toHaveTextContent("Loading…");
    expect(screen.getByRole("status")).toHaveAttribute("aria-live", "polite");
    expect(screen.getByTestId("artwork-spinner")).toHaveAttribute("data-visible", "true");
  });

  it("tells a slow connection apart", () => {
    renderNowPlaying({ player_state: "BUFFERING", stalled_since: STALLED });
    expect(screen.getByRole("status")).toHaveTextContent("Slow connection, still loading…");
  });

  it("shows the reconnect attempt and keeps the title while the server recovers the stream", () => {
    renderNowPlaying({ player_state: "IDLE", idle_reason: "ERROR", recovering: true, recovery_attempt: 1 });
    expect(screen.getByRole("status")).toHaveTextContent("Reconnecting… attempt 1/3");
    expect(screen.getByRole("heading", { name: "Rai 1 HD" })).toBeInTheDocument();
    expect(screen.getByTestId("artwork-spinner")).toHaveAttribute("data-visible", "true");
    // the user can still stop it
    expect(screen.getByRole("button", { name: "Stop" })).toBeEnabled();
  });

  it("hides the spinner and shows the receiver while playing", () => {
    renderNowPlaying();
    expect(screen.getByRole("status")).toHaveTextContent("Default Media Receiver");
    expect(screen.getByTestId("artwork-spinner")).toHaveAttribute("data-visible", "false");
  });

  it("is translated in Italian", () => {
    useLocaleStore.setState({ locale: "it", hydrated: true });
    const { unmount } = renderNowPlaying({ player_state: "IDLE", recovering: true, recovery_attempt: 2 });
    expect(screen.getByRole("status")).toHaveTextContent("Riconnessione… tentativo 2/3");
    unmount();
    renderNowPlaying({ player_state: "BUFFERING", stalled_since: STALLED });
    expect(screen.getByRole("status")).toHaveTextContent("Connessione lenta, sto ancora caricando…");
  });
});

describe("MiniPlayer loading indicator", () => {
  it("swaps the device name for the status line while reconnecting", () => {
    setPlayer({ player_state: "IDLE", recovering: true, recovery_attempt: 3 });
    renderWithProviders(<MiniPlayer visible />);
    expect(screen.getByTestId("mini-status")).toHaveTextContent("Reconnecting… attempt 3/3");
    expect(screen.getByTestId("mini-title")).toHaveTextContent("Rai 1 HD");
    expect(screen.getByTestId("artwork-spinner")).toHaveAttribute("data-visible", "true");
  });

  it("shows the device name when playing normally", () => {
    setPlayer({});
    renderWithProviders(<MiniPlayer visible />);
    expect(screen.getByTestId("mini-status")).toHaveTextContent("Salotto");
    expect(screen.getByTestId("artwork-spinner")).toHaveAttribute("data-visible", "false");
  });
});

describe("optimistic loading after cast", () => {
  const wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={new QueryClient()}>{children}</QueryClientProvider>
  );

  it("shows loading from the tap until the first PLAYING snapshot", async () => {
    setPlayer({ player_state: "IDLE", title: null });
    let answer!: (p: PlayerState) => void;
    vi.spyOn(api.player, "play").mockReturnValue(new Promise<PlayerState>((r) => (answer = r)));
    const { result } = renderHook(() => useCast(), { wrapper });
    renderWithProviders(<MiniPlayer visible />);

    let done!: Promise<unknown>;
    act(() => {
      done = result.current.cast({ input: "http://x/live.m3u8" });
    });
    await vi.waitFor(() => expect(useAppStore.getState().pendingLoad["dev-1"]).toBeTruthy());
    expect(screen.getByTestId("mini-status")).toHaveTextContent("Loading…");

    await act(async () => {
      answer(makePlayer({ player_state: "BUFFERING" }));
      await done;
    });
    expect(screen.getByTestId("mini-status")).toHaveTextContent("Loading…");
    act(() => setPlayer({ player_state: "PLAYING" }));
    expect(useAppStore.getState().pendingLoad).toEqual({});
    expect(screen.getByTestId("mini-status")).toHaveTextContent("Salotto");
  });

  it("drops the optimistic state when the cast fails", async () => {
    setPlayer({ player_state: "IDLE" });
    vi.spyOn(api.player, "play").mockRejectedValue(new Error("boom"));
    const { result } = renderHook(() => useCast(), { wrapper });
    await act(async () => {
      await result.current.cast({ input: "http://x/live.m3u8" });
    });
    expect(useAppStore.getState().pendingLoad).toEqual({});
  });
});

describe("recovery toasts", () => {
  it("are translated by code", () => {
    useLocaleStore.setState({ locale: "it", hydrated: true });
    expect(
      toastText({
        type: "toast",
        level: "info",
        message: "Stream interrupted, reconnecting… (1/3)",
        code: "stream_reconnecting",
        params: { title: "Rai 1", attempt: 1, max: 3 },
      }),
    ).toBe("Stream interrotto, riconnessione… (1/3)");
    useLocaleStore.setState({ locale: "en", hydrated: true });
    expect(
      toastText({ type: "toast", level: "success", message: "Stream restored", code: "stream_restored", params: {} }),
    ).toBe("Stream restored");
  });
});
