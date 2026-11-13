import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { CapturedList } from "@/components/browser/captured-list";
import { LocalPlayerContent, qualityName } from "@/components/player/local-player-sheet";
import { api } from "@/lib/api";
import { engineKindFor } from "@/lib/local-player/engine";
import { MediaActions } from "@/components/cast/media-actions";
import { NowPlayingContent } from "@/components/player/now-playing";
import { capturedMedia, seekAfterCast, tvMedia } from "@/lib/local-player/sources";
import { useLocalPlayerStore, type LocalMedia } from "@/stores/local-player-store";
import { makeCaptured, makeDevice, makePlayer } from "./fixtures";
import { renderWithProviders } from "./render";

afterEach(() => vi.restoreAllMocks());
// jsdom only logs "Not implemented" for load(); the engines call it when tearing a source down
HTMLMediaElement.prototype.load = () => {};

describe("engine choice", () => {
  it("uses dash.js for DASH, hls.js for HLS (it has the renditions/tracks), the element otherwise", () => {
    expect(engineKindFor("/proxy/t/live.mpd", null)).toBe("dash");
    expect(engineKindFor("/proxy/t/token-abc", "application/dash+xml")).toBe("dash");
    expect(engineKindFor("/proxy/t/index.m3u8", null)).toBe("hls");
    expect(engineKindFor("/proxy/t/token-abc", "application/x-mpegURL")).toBe("hls");
    expect(engineKindFor("/proxy/t/movie.mp4", "video/mp4")).toBe("native");
  });

  it("names qualities by height, else by bitrate", () => {
    expect(qualityName({ id: 0, height: 1080, bitrate: 5e6 })).toBe("1080p");
    expect(qualityName({ id: 1, height: null, bitrate: 2_500_000 })).toBe("2.5 Mbps");
    expect(qualityName({ id: 2, height: null, bitrate: 128_000 })).toBe("128 kbps");
    const twins = [
      { id: 3, height: 360, bitrate: 1_200_000 },
      { id: 4, height: 360, bitrate: 800_000 },
    ];
    expect(qualityName(twins[0], twins)).toBe("360p · 1.2 Mbps");
  });
});

describe("capturedMedia", () => {
  it("trusts the detected kind over a missing/disguised extension", () => {
    const m = capturedMedia(
      makeCaptured({ kind: "hls", mime_type: "video/mp4", url: "https://edge.example/token-abc", preview_url: "/proxy/t/res" }),
    );
    expect(m.source).toEqual({ src: "/proxy/t/res", mimeType: "application/x-mpegURL" });
  });

  it("asks the resolver when the capture has no preview path", async () => {
    const resolve = vi.spyOn(api.resolver, "resolve").mockResolvedValue({
      type: "media",
      media: { preview_url: "/proxy/x/clip.mp4", mime_type: "video/mp4" },
    } as Awaited<ReturnType<typeof api.resolver.resolve>>);
    const m = capturedMedia(makeCaptured({ url: "https://cdn.example/clip.mp4", preview_url: null }));
    expect(typeof m.source).toBe("function");
    const src = await (m.source as (s: AbortSignal) => Promise<unknown>)(new AbortController().signal);
    expect(resolve).toHaveBeenCalledWith("https://cdn.example/clip.mp4", "direct", expect.anything());
    expect(src).toEqual({ src: "/proxy/x/clip.mp4", mimeType: "video/mp4" });
  });
});

describe("LocalPlayerContent", () => {
  const media = (over: Partial<LocalMedia> = {}): LocalMedia => ({
    title: "Aurora Live",
    subtitle: "demo-tv.example",
    source: { src: "http://cdn.example/clip.mp4", mimeType: "video/mp4" },
    ...over,
  });

  it("plays a progressive source on the page and sends it to the TV", async () => {
    const onCast = vi.fn();
    const onClose = vi.fn();
    render(<LocalPlayerContent media={media({ onCast })} onClose={onClose} />);
    const el = screen.getByTestId("local-video") as HTMLVideoElement;
    await waitFor(() => expect(el.getAttribute("src")).toBe("http://cdn.example/clip.mp4"));
    expect(screen.getByRole("heading", { name: "Aurora Live" })).toBeInTheDocument();

    fireEvent.canPlay(el);
    expect(HTMLMediaElement.prototype.play).toHaveBeenCalled();

    fireEvent.click(screen.getByRole("button", { name: /Send to TV/ }));
    expect(onCast).toHaveBeenCalledTimes(1);
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("shows the error with a retry that reloads the source", async () => {
    render(<LocalPlayerContent media={media()} />);
    const el = screen.getByTestId("local-video") as HTMLVideoElement;
    await waitFor(() => expect(el.getAttribute("src")).toBeTruthy());
    act(() => {
      fireEvent.error(el);
    });
    expect(screen.getByRole("alert")).toHaveTextContent("Can’t play this stream here");
    fireEvent.click(screen.getByRole("button", { name: /Retry/ }));
    await waitFor(() => expect(screen.queryByRole("alert")).not.toBeInTheDocument());
    expect(el.getAttribute("src")).toBe("http://cdn.example/clip.mp4");
  });

  it("reports a source that can't be resolved", async () => {
    render(<LocalPlayerContent media={media({ source: () => Promise.reject(new Error()) })} />);
    expect(await screen.findByRole("alert")).toHaveTextContent("Can’t play this stream here");
  });
});

describe("Watch here entry point", () => {
  it("is offered for every captured stream", () => {
    const onWatch = vi.fn();
    const s = makeCaptured();
    render(<CapturedList streams={[s]} onPreview={vi.fn()} onCast={vi.fn()} onWatch={onWatch} />);
    fireEvent.click(screen.getByRole("button", { name: /^Watch .* here$/ }));
    expect(onWatch).toHaveBeenCalledWith(s);
  });
});

describe("switching between the TV and this device", () => {
  it("offers Watch here next to the cast actions", () => {
    const onWatch = vi.fn();
    render(<MediaActions onCast={vi.fn()} onWatch={onWatch} />);
    fireEvent.click(screen.getByRole("button", { name: "Watch here" }));
    expect(onWatch).toHaveBeenCalledTimes(1);
  });

  it("continues what the TV plays: from its position, and back to the TV from the local one", async () => {
    const control = vi.spyOn(api.player, "control").mockImplementation(async (id) => makePlayer({ device_id: id }));
    const media = tvMedia("tv-1", makePlayer({ original_input: "https://youtu.be/abc", stream_type: "BUFFERED" }), 42)!;
    expect(media.startAt).toBe(42);
    media.onCast!(95);
    await waitFor(() => expect(control).toHaveBeenCalledWith("tv-1", "play", undefined));
    expect(control.mock.calls.map((c) => c.slice(1, 3))).toEqual([["seek", 95], ["play", undefined]]);

    control.mockClear();
    const live = tvMedia("tv-1", makePlayer({ original_input: "https://cdn.example/live.m3u8", stream_type: "LIVE" }), 300)!;
    expect(live.startAt).toBeNull();
    live.onCast!(null);
    await waitFor(() => expect(control).toHaveBeenCalledWith("tv-1", "play", undefined));
    expect(control.mock.calls[0].slice(1, 2)).toEqual(["go_live"]);

    expect(tvMedia("tv-1", makePlayer({ original_input: null }), 0)).toBeNull();
  });

  it("seeks the TV after a cast only when there is a position worth resuming", async () => {
    const control = vi.spyOn(api.player, "control").mockImplementation(async (id) => makePlayer({ device_id: id }));
    await seekAfterCast(makePlayer({ device_id: "tv-1" }), 2);
    await seekAfterCast(makePlayer({ device_id: "tv-1" }), null);
    await seekAfterCast(null, 120);
    expect(control).not.toHaveBeenCalled();
    await seekAfterCast(makePlayer({ device_id: "tv-1" }), 120);
    expect(control).toHaveBeenCalledWith("tv-1", "seek", 120);
  });

  it("Now Playing hands the TV's media over to this device", async () => {
    const control = vi.spyOn(api.player, "control").mockImplementation(async (id) => makePlayer({ device_id: id }));
    const player = makePlayer({ player_state: "PLAYING", original_input: "https://youtu.be/abc", title: "Highlights" });
    const device = makeDevice({ id: player.device_id });
    renderWithProviders(<NowPlayingContent device={device} player={player} receivedAt={Date.now()} />);
    fireEvent.click(screen.getByRole("button", { name: /Watch on this device/ }));
    await waitFor(() => expect(control).toHaveBeenCalledWith(device.id, "pause", undefined));
    expect(useLocalPlayerStore.getState().media?.title).toBe("Highlights");
    act(() => useLocalPlayerStore.getState().close());
  });
});
