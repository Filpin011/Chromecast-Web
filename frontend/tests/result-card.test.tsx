import { fireEvent, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("sonner", () => {
  const toast = Object.assign(vi.fn(), { error: vi.fn(), success: vi.fn(), loading: vi.fn() });
  return { toast };
});
vi.mock("next/navigation", () => ({
  usePathname: () => "/",
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
  useSearchParams: () => new URLSearchParams(),
}));
// the real preview would load hls.js; a marker is enough to know whether the stream is being pulled
vi.mock("@/components/media/video-preview", () => ({
  VideoPreview: ({ src }: { src: string }) => <div data-testid="video-preview" data-src={src} />,
}));

import { MediaResultCard, ResolveErrorCard } from "@/components/cast/result-card";
import { api, ApiError } from "@/lib/api";
import type { ResolvedMedia } from "@/lib/api/types";
import { useAppStore } from "@/stores/app-store";
import { makeAppState, makePlayer } from "./fixtures";
import { renderWithProviders } from "./render";

const media: ResolvedMedia = {
  url: "http://iptv.example/live/1.m3u8",
  cast_url: "http://192.168.1.10:8000/proxy/t/master.m3u8",
  preview_url: "/proxy/t/master.m3u8",
  title: "Canale 1",
  mime_type: "application/x-mpegURL",
  stream_type: "LIVE",
  thumbnail: null,
  source_kind: "m3u",
  original_input: "http://iptv.example/live/1.m3u8",
  proxied: true,
  subtitles: [],
  hls_segment_format: null,
};

beforeEach(() => {
  vi.restoreAllMocks();
  useAppStore.getState().reset();
  useAppStore.getState().applySnapshot(makeAppState());
});

describe("MediaResultCard preview", () => {
  it("does not pull the stream until the user asks for a preview", () => {
    renderWithProviders(<MediaResultCard media={media} />);
    expect(screen.queryByTestId("video-preview")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Preview on this phone" }));
    expect(screen.getByTestId("video-preview")).toHaveAttribute("data-src", "/proxy/t/master.m3u8");
  });

  it("stops the preview when casting so the Chromecast gets the connection", async () => {
    const play = vi.spyOn(api.player, "play").mockResolvedValue(makePlayer());
    renderWithProviders(<MediaResultCard media={media} />);
    fireEvent.click(screen.getByRole("button", { name: "Preview on this phone" }));
    expect(screen.getByTestId("video-preview")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /Cast now/ }));
    expect(screen.queryByTestId("video-preview")).not.toBeInTheDocument();
    await waitFor(() => expect(play).toHaveBeenCalled());
  });
});

describe("ResolveErrorCard", () => {
  const noStream = new ApiError(422, "x", "resolve_failed", "no_stream_on_page");
  const unreachable = new ApiError(502, "x", "resolve_failed", "connect_failed", { host: "127.0.0.1" });

  it("keeps the recovery buttons full height on phones (no flex-1 in the column layout)", () => {
    renderWithProviders(<ResolveErrorCard error={noStream} input="https://site.example/watch" onRetry={vi.fn()} />);
    for (const name of [/Open in the interactive browser/, /Cast anyway/]) {
      const btn = screen.getByRole("button", { name });
      // flex-basis 0 in a flex-col container overrides h-12 and collapses the button to its text
      expect(btn.className).not.toMatch(/(^|\s)flex-1(\s|$)/);
      expect(btn.className).toContain("sm:flex-1");
      expect(btn.className).toContain("h-12");
    }
  });

  it("offers the interactive browser first when the page loaded but had no video", () => {
    renderWithProviders(<ResolveErrorCard error={noStream} input="https://site.example/watch" onRetry={vi.fn()} />);
    expect(screen.getByText("No video found automatically")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Retry" })).not.toBeInTheDocument();
    const buttons = screen.getAllByRole("button");
    expect(buttons[0]).toHaveAccessibleName("Open in the interactive browser");
  });

  it("says the site is unreachable and offers retry instead of the browser", () => {
    const onRetry = vi.fn();
    renderWithProviders(<ResolveErrorCard error={unreachable} input="http://127.0.0.1:1/nothing" onRetry={onRetry} />);
    expect(screen.getByText("Couldn’t reach the site")).toBeInTheDocument();
    expect(screen.getByText("Couldn’t connect to 127.0.0.1")).toBeInTheDocument();
    expect(screen.queryByText("No video found automatically")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /interactive browser/ })).not.toBeInTheDocument();
    const buttons = screen.getAllByRole("button");
    expect(buttons[0]).toHaveAccessibleName("Retry");
    fireEvent.click(buttons[0]);
    expect(onRetry).toHaveBeenCalledOnce();
    expect(screen.getByRole("button", { name: "Cast anyway" })).toBeInTheDocument();
  });

  it("disables retry while the new attempt runs", () => {
    renderWithProviders(<ResolveErrorCard error={unreachable} input="http://127.0.0.1:1/" onRetry={vi.fn()} retrying />);
    expect(screen.getByRole("button", { name: "Retry" })).toBeDisabled();
  });

  it("keeps the browser as a fallback after an HTTP error (a real browser may get through)", () => {
    const http = new ApiError(502, "x", "resolve_failed", "upstream_http", { status: 403 });
    renderWithProviders(<ResolveErrorCard error={http} input="https://site.example/" onRetry={vi.fn()} />);
    expect(screen.getByText("The site returned an error")).toBeInTheDocument();
    const buttons = screen.getAllByRole("button");
    expect(buttons.map((b) => b.textContent)).toEqual(["Retry", "Open in the interactive browser", "Cast anyway"]);
  });
});
