import { act, fireEvent, screen, waitFor } from "@testing-library/react";
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

import CastPage from "@/app/page";
import { api } from "@/lib/api";
import { renderWithProviders } from "./render";

const media = {
  type: "media" as const,
  media: {
    url: "http://x/live.m3u8",
    cast_url: "http://x/live.m3u8",
    preview_url: "http://x/live.m3u8",
    title: "Live",
    mime_type: "application/x-mpegURL",
    stream_type: "LIVE" as const,
    thumbnail: null,
    source_kind: "direct" as const,
    original_input: "http://x/live.m3u8",
    proxied: false,
    subtitles: [],
    hls_segment_format: null,
  },
};

beforeEach(() => {
  vi.restoreAllMocks();
  vi.spyOn(api.history, "list").mockResolvedValue([]);
  vi.spyOn(api.favorites, "list").mockResolvedValue([]);
});

const box = () => screen.getByLabelText("URL, playlist o link video");
const pause = () => act(() => new Promise((r) => setTimeout(r, 900)));

describe("Cast page resolve policy", () => {
  it("does not resolve a half-typed web page URL after a typing pause", async () => {
    const resolve = vi.spyOn(api.resolver, "resolve").mockResolvedValue(media);
    renderWithProviders(<CastPage />);
    fireEvent.change(box(), { target: { value: "https://site.com/pag" } });
    await pause();
    expect(resolve).not.toHaveBeenCalled();
    expect(screen.getByTestId("input-hint")).toHaveTextContent("Invio");
    fireEvent.keyDown(box(), { key: "Enter" });
    await waitFor(() => expect(resolve).toHaveBeenCalledWith("https://site.com/pag", undefined, expect.anything()));
  });

  it("auto-resolves direct streams while typing and pasted page URLs at once", async () => {
    const resolve = vi.spyOn(api.resolver, "resolve").mockResolvedValue(media);
    renderWithProviders(<CastPage />);
    fireEvent.change(box(), { target: { value: "http://x/live.m3u8" } });
    await waitFor(() => expect(resolve).toHaveBeenCalledTimes(1), { timeout: 2000 });
    fireEvent.paste(box());
    fireEvent.change(box(), { target: { value: "https://site.com/page" } });
    await waitFor(() => expect(resolve).toHaveBeenLastCalledWith("https://site.com/page", undefined, expect.anything()));
  });
});
