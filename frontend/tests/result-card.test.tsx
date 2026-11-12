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

import { MediaResultCard } from "@/components/cast/result-card";
import { api } from "@/lib/api";
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
    fireEvent.click(screen.getByRole("button", { name: "Anteprima sul telefono" }));
    expect(screen.getByTestId("video-preview")).toHaveAttribute("data-src", "/proxy/t/master.m3u8");
  });

  it("stops the preview when casting so the Chromecast gets the connection", async () => {
    const play = vi.spyOn(api.player, "play").mockResolvedValue(makePlayer());
    renderWithProviders(<MediaResultCard media={media} />);
    fireEvent.click(screen.getByRole("button", { name: "Anteprima sul telefono" }));
    expect(screen.getByTestId("video-preview")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /Trasmetti ora/ }));
    expect(screen.queryByTestId("video-preview")).not.toBeInTheDocument();
    await waitFor(() => expect(play).toHaveBeenCalled());
  });
});
