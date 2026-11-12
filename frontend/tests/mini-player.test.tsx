import { act, fireEvent, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("sonner", () => {
  const toast = Object.assign(vi.fn(), { error: vi.fn(), success: vi.fn(), loading: vi.fn() });
  return { toast };
});

import { toast } from "sonner";
import { MiniPlayer } from "@/components/player/mini-player";
import { NowPlayingContent } from "@/components/player/now-playing";
import { api } from "@/lib/api";
import { useAppStore } from "@/stores/app-store";
import { useUiStore } from "@/stores/ui-store";
import { makeAppState, makeDevice, makePlayer } from "./fixtures";
import { renderWithProviders } from "./render";

function deferred<T>() {
  let resolve!: (v: T) => void;
  let reject!: (e: unknown) => void;
  const promise = new Promise<T>((res, rej) => {
    resolve = res;
    reject = rej;
  });
  return { promise, resolve, reject };
}

beforeEach(() => {
  useAppStore.getState().reset();
  useAppStore.getState().applySnapshot(makeAppState());
  useUiStore.setState({ nowPlayingOpen: false });
});

describe("MiniPlayer", () => {
  it("shows the current title, device and live badge", () => {
    renderWithProviders(<MiniPlayer visible />);
    expect(screen.getByTestId("mini-title")).toHaveTextContent("Rai 1 HD");
    expect(screen.getByText("Salotto")).toBeInTheDocument();
    expect(screen.getByText("Live")).toBeInTheDocument();
  });

  it("renders nothing when hidden", () => {
    renderWithProviders(<MiniPlayer visible={false} />);
    expect(screen.queryByTestId("mini-title")).not.toBeInTheDocument();
  });

  it("toggles playback optimistically and settles with the server answer", async () => {
    const d = deferred<ReturnType<typeof makePlayer>>();
    const control = vi.spyOn(api.player, "control").mockReturnValue(d.promise);
    renderWithProviders(<MiniPlayer visible />);
    fireEvent.click(screen.getByRole("button", { name: "Pausa" }));
    expect(control).toHaveBeenCalledWith("dev-1", "toggle", undefined);
    // optimistic: already shows the play icon
    expect(screen.getByRole("button", { name: "Riproduci" })).toBeInTheDocument();
    await act(async () => d.resolve(makePlayer({ player_state: "PAUSED" })));
    expect(screen.getByRole("button", { name: "Riproduci" })).toBeInTheDocument();
    expect(useAppStore.getState().optimistic).toEqual({});
    expect(useUiStore.getState().nowPlayingOpen).toBe(false);
  });

  it("reverts and toasts when the command fails", async () => {
    vi.spyOn(api.player, "control").mockRejectedValue(new Error("Dispositivo non connesso"));
    renderWithProviders(<MiniPlayer visible />);
    fireEvent.click(screen.getByRole("button", { name: "Pausa" }));
    await waitFor(() => expect(toast.error).toHaveBeenCalledWith("Dispositivo non connesso"));
    expect(screen.getByRole("button", { name: "Pausa" })).toBeInTheDocument();
  });

  it("expands into Now Playing on tap", () => {
    renderWithProviders(<MiniPlayer visible />);
    fireEvent.click(screen.getByRole("button", { name: "Apri player" }));
    expect(useUiStore.getState().nowPlayingOpen).toBe(true);
  });

  it("Enter on the play/pause button toggles playback and does not open Now Playing", async () => {
    const user = userEvent.setup();
    const control = vi.spyOn(api.player, "control").mockResolvedValue(makePlayer({ player_state: "PAUSED" }));
    renderWithProviders(<MiniPlayer visible />);
    screen.getByRole("button", { name: "Pausa" }).focus();
    await user.keyboard("{Enter}");
    expect(control).toHaveBeenCalledWith("dev-1", "toggle", undefined);
    expect(useUiStore.getState().nowPlayingOpen).toBe(false);
  });

  it("opens Now Playing from the keyboard, with play/pause as a sibling (no nested controls)", async () => {
    const user = userEvent.setup();
    renderWithProviders(<MiniPlayer visible />);
    const opener = screen.getByRole("button", { name: "Apri player" });
    expect(opener.tagName).toBe("BUTTON");
    expect(opener).not.toContainElement(screen.getByRole("button", { name: "Pausa" }));
    opener.focus();
    await user.keyboard("{Enter}");
    expect(useUiStore.getState().nowPlayingOpen).toBe(true);
  });
});

describe("NowPlayingContent", () => {
  it("offers 'go live' for live streams", () => {
    const control = vi.spyOn(api.player, "control").mockResolvedValue(makePlayer());
    renderWithProviders(<NowPlayingContent device={makeDevice()} player={makePlayer()} receivedAt={Date.now()} />);
    fireEvent.click(screen.getByRole("button", { name: /Vai al live/ }));
    expect(control).toHaveBeenCalledWith("dev-1", "go_live", undefined);
  });

  it("shows a seek bar and skip buttons for VOD", () => {
    const control = vi.spyOn(api.player, "control").mockResolvedValue(makePlayer());
    const vod = makePlayer({ stream_type: "BUFFERED", duration: 600, seekable: true, current_time: 65 });
    renderWithProviders(<NowPlayingContent device={makeDevice()} player={vod} receivedAt={Date.now()} />);
    // the focusable range input itself carries the name and a readable value
    // (by label, not role+name: Base UI keeps the thumb visibility:hidden until it can measure layout,
    // which jsdom never does, and hidden nodes get an empty computed name)
    const seek = screen.getByLabelText("Posizione");
    expect(seek).toHaveAttribute("type", "range");
    expect(seek).toHaveAttribute("aria-valuetext", "1:05 di 10:00");
    expect(screen.getByText("1:05")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Indietro 10 secondi" }));
    fireEvent.click(screen.getByRole("button", { name: "Avanti 30 secondi" }));
    expect(control).toHaveBeenNthCalledWith(1, "dev-1", "seek_relative", -10);
    expect(control).toHaveBeenNthCalledWith(2, "dev-1", "seek_relative", 30);
  });

  it("names the volume slider for assistive tech", () => {
    renderWithProviders(<NowPlayingContent device={makeDevice()} player={makePlayer()} receivedAt={Date.now()} />);
    const volume = screen.getByLabelText("Volume");
    expect(volume).toHaveAttribute("type", "range");
    expect(volume).toHaveAttribute("aria-valuetext", "50%");
  });

  it("lets 'Precedente' restart or go back while playing, but not when idle", () => {
    const control = vi.spyOn(api.player, "control").mockResolvedValue(makePlayer());
    const { unmount } = renderWithProviders(
      <NowPlayingContent device={makeDevice()} player={makePlayer()} receivedAt={Date.now()} />,
    );
    fireEvent.click(screen.getByRole("button", { name: "Precedente" }));
    expect(control).toHaveBeenCalledWith("dev-1", "previous", undefined);
    unmount();
    renderWithProviders(
      <NowPlayingContent device={makeDevice()} player={makePlayer({ player_state: "IDLE" })} receivedAt={Date.now()} />,
    );
    expect(screen.queryByRole("button", { name: "Precedente" })).not.toBeInTheDocument();
  });

  it("mutes, stops and shows the idle image", async () => {
    const control = vi.spyOn(api.player, "control").mockResolvedValue(makePlayer());
    const idle = vi.spyOn(api.player, "showIdle").mockResolvedValue(makePlayer({ showing_idle_image: true }));
    renderWithProviders(<NowPlayingContent device={makeDevice()} player={makePlayer()} receivedAt={Date.now()} />);
    fireEvent.click(screen.getByRole("button", { name: "Muto" }));
    fireEvent.click(screen.getByRole("button", { name: /Stop/ }));
    fireEvent.click(screen.getByRole("button", { name: /Immagine attesa/ }));
    expect(control).toHaveBeenCalledWith("dev-1", "mute", undefined);
    expect(control).toHaveBeenCalledWith("dev-1", "stop", undefined);
    await waitFor(() => expect(idle).toHaveBeenCalledWith("dev-1"));
  });

  it("does not present the idle image as live playback", () => {
    const idle = makePlayer({ showing_idle_image: true, player_state: "PLAYING", title: null, duration: null });
    renderWithProviders(<NowPlayingContent device={makeDevice()} player={idle} receivedAt={Date.now()} />);
    expect(screen.getByRole("heading", { name: "Immagine di attesa" })).toBeInTheDocument();
    expect(screen.queryByText(/^live$/i)).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Vai al live/ })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Pausa" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Riproduci" })).toBeDisabled();
    expect(screen.getByRole("button", { name: /Indietro 10 secondi/ })).toBeDisabled();
  });

  it("lists and removes queue items", async () => {
    const remove = vi.spyOn(api.player, "removeFromQueue").mockResolvedValue(makePlayer());
    const player = makePlayer({ queue: [{ id: "q1", input: "a", title: "Prossimo film", thumbnail: null }] });
    renderWithProviders(<NowPlayingContent device={makeDevice()} player={player} receivedAt={Date.now()} />);
    fireEvent.click(screen.getByRole("button", { name: /Coda/ }));
    expect(screen.getByText("Prossimo film")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Rimuovi Prossimo film" }));
    await waitFor(() => expect(remove).toHaveBeenCalledWith("dev-1", "q1"));
  });
});
