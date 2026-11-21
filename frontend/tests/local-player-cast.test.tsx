import { act, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { useEffect } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("sonner", () => {
  const toast = Object.assign(vi.fn(), { error: vi.fn(), success: vi.fn(), loading: vi.fn().mockReturnValue("t1") });
  return { toast };
});

import { toast } from "sonner";
import { DevicePickerSheet } from "@/components/devices/device-picker-sheet";
import { LocalPlayerSheet } from "@/components/player/local-player-sheet";
import { useCast } from "@/hooks/use-cast";
import { api } from "@/lib/api";
import { useAppStore } from "@/stores/app-store";
import { openLocalPlayer, useLocalPlayerStore } from "@/stores/local-player-store";
import { useUiStore } from "@/stores/ui-store";
import { makeAppState, makePlayer } from "./fixtures";
import { renderWithProviders } from "./render";

// jsdom only logs "Not implemented" for load(); the engines call it when tearing a source down
HTMLMediaElement.prototype.load = () => {};

const MOVIE = "https://cdn.example/movie.mp4";

/** Opens the local player the way the app does, with "Send to TV" going through `useCast`. */
function Opener() {
  const { cast } = useCast();
  useEffect(() => {
    openLocalPlayer({
      title: "Big Movie",
      source: { src: "http://cdn.example/clip.mp4", mimeType: "video/mp4" },
      onCast: () => void cast({ input: MOVIE, title: "Big Movie" }),
    });
  }, [cast]);
  return null;
}

function renderApp() {
  return renderWithProviders(
    <>
      <Opener />
      <LocalPlayerSheet />
      <DevicePickerSheet />
    </>,
  );
}

const sendButton = () => screen.getByRole("button", { name: /Send to TV/ });
const playerOpen = () => useLocalPlayerStore.getState().media !== null;

function snapshot(version: number, player: Parameters<typeof makePlayer>[0]) {
  act(() => useAppStore.getState().applySnapshot(makeAppState({ version, players: { "dev-1": makePlayer(player) } })));
}

beforeEach(() => {
  useAppStore.getState().reset();
  useUiStore.setState({ devicePickerOpen: false, pendingDevice: null, nowPlayingOpen: false });
  vi.mocked(toast.error).mockClear();
});

afterEach(() => {
  act(() => useLocalPlayerStore.getState().close());
  vi.restoreAllMocks();
});

describe("Send to TV from the local player", () => {
  it("stays open and playing while sending, and closes once that device plays the new media", async () => {
    // the TV was playing something else; the active device casts straight away (no picker)
    useAppStore.getState().applySnapshot(makeAppState());
    const play = vi
      .spyOn(api.player, "play")
      .mockResolvedValue(makePlayer({ player_state: "BUFFERING", original_input: MOVIE, media_url: MOVIE }));
    renderApp();
    const video = (await screen.findByTestId("local-video")) as HTMLVideoElement;
    vi.mocked(HTMLMediaElement.prototype.pause).mockClear();

    fireEvent.click(sendButton());
    await waitFor(() => expect(play).toHaveBeenCalledWith("dev-1", expect.objectContaining({ input: MOVIE })));
    expect(useUiStore.getState().devicePickerOpen).toBe(false);

    const status = await screen.findByText("Sending to Salotto…");
    expect(status.closest("[role=status]")).toHaveAttribute("aria-live", "polite");
    expect(sendButton()).toBeDisabled();
    expect(playerOpen()).toBe(true);
    expect(video).toBeInTheDocument();
    expect(HTMLMediaElement.prototype.pause).not.toHaveBeenCalled();

    // a snapshot of what the TV played before is not the cast landing
    snapshot(2, { player_state: "PLAYING" });
    expect(playerOpen()).toBe(true);

    snapshot(3, { player_state: "PLAYING", original_input: MOVIE, media_url: MOVIE });
    await waitFor(() => expect(playerOpen()).toBe(false));
    expect(HTMLMediaElement.prototype.pause).toHaveBeenCalled();
  });

  it("opens the device picker over the player, then casts to the chosen device", async () => {
    useAppStore.getState().applySnapshot(makeAppState({ active_device_id: null, players: {} }));
    const play = vi.spyOn(api.player, "play").mockResolvedValue(makePlayer({ player_state: "BUFFERING", original_input: MOVIE }));
    renderApp();
    await screen.findByTestId("local-video");

    fireEvent.click(sendButton());
    const picker = await screen.findByRole("dialog", { name: "Send video to…" });
    expect(playerOpen()).toBe(true);
    expect(screen.getByTestId("local-video")).toBeInTheDocument();

    fireEvent.click(within(picker).getByText("Salotto"));
    await waitFor(() => expect(play).toHaveBeenCalledWith("dev-1", expect.anything()));
    expect(await screen.findByText("Sending to Salotto…")).toBeInTheDocument();
    expect(playerOpen()).toBe(true);

    snapshot(2, { player_state: "PLAYING", original_input: MOVIE });
    await waitFor(() => expect(playerOpen()).toBe(false));
  });

  it("cancelling the picker leaves the player as it was", async () => {
    useAppStore.getState().applySnapshot(makeAppState({ active_device_id: null, players: {} }));
    const play = vi.spyOn(api.player, "play");
    renderApp();
    await screen.findByTestId("local-video");

    fireEvent.click(sendButton());
    const picker = await screen.findByRole("dialog", { name: "Send video to…" });
    fireEvent.click(within(picker).getByRole("button", { name: "Cancel" }));

    await waitFor(() => expect(useUiStore.getState().devicePickerOpen).toBe(false));
    expect(playerOpen()).toBe(true);
    expect(play).not.toHaveBeenCalled();
    await waitFor(() => expect(sendButton()).toBeEnabled());
    expect(screen.queryByText(/Sending to/)).not.toBeInTheDocument();
    expect(toast.error).not.toHaveBeenCalled();
  });

  it("stays open with an error when the cast request fails", async () => {
    useAppStore.getState().applySnapshot(makeAppState());
    vi.spyOn(api.player, "play").mockRejectedValue(new Error("Device unreachable"));
    renderApp();
    await screen.findByTestId("local-video");

    fireEvent.click(sendButton());
    expect(await screen.findByText("Device unreachable")).toBeInTheDocument();
    expect(toast.error).toHaveBeenCalled();
    expect(playerOpen()).toBe(true);
    expect(sendButton()).toBeEnabled();
  });

  it("stays open with an error when the receiver goes idle instead of playing", async () => {
    useAppStore.getState().applySnapshot(makeAppState());
    vi.spyOn(api.player, "play").mockResolvedValue(makePlayer({ player_state: "BUFFERING", original_input: MOVIE }));
    renderApp();
    await screen.findByTestId("local-video");

    fireEvent.click(sendButton());
    await screen.findByText("Sending to Salotto…");
    snapshot(2, { player_state: "IDLE", idle_reason: "ERROR", original_input: MOVIE });

    expect(await screen.findByText("Salotto didn’t start playing. Still playing on this device.")).toBeInTheDocument();
    expect(toast.error).toHaveBeenCalledWith("Salotto didn’t start playing. Still playing on this device.");
    expect(playerOpen()).toBe(true);
    expect(sendButton()).toBeEnabled();
  });

  it("gives up after the timeout when the Chromecast never plays", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    try {
      useAppStore.getState().applySnapshot(makeAppState());
      vi.spyOn(api.player, "play").mockResolvedValue(makePlayer({ player_state: "BUFFERING", original_input: MOVIE }));
      renderApp();
      await screen.findByTestId("local-video");
      fireEvent.click(sendButton());
      await screen.findByText("Sending to Salotto…");
      act(() => vi.advanceTimersByTime(46_000));
      expect(await screen.findByText(/didn’t start playing/)).toBeInTheDocument();
      expect(playerOpen()).toBe(true);
    } finally {
      vi.useRealTimers();
    }
  });
});
