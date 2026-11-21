import { fireEvent, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("sonner", () => {
  const toast = Object.assign(vi.fn(), { error: vi.fn(), success: vi.fn(), loading: vi.fn() });
  return { toast };
});
let search = new URLSearchParams();
vi.mock("next/navigation", () => ({
  usePathname: () => "/playlists/view/",
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
  useSearchParams: () => search,
}));

import PlaylistViewPage from "@/app/playlists/view/page";
import { ImportPlaylistDialog } from "@/components/playlists/import-dialog";
import { api, ApiError } from "@/lib/api";
import type { Playlist } from "@/lib/api/types";
import { embeddedPlaylistName, importedPlaylistName } from "@/lib/playlist-import";
import { renderWithProviders } from "./render";

const PLAYLIST: Playlist = {
  id: "p1",
  name: "x",
  source_url: null,
  channel_count: 1,
  groups: [],
  created_at: "2026-11-21T10:00:00Z",
  updated_at: "2026-11-21T10:00:00Z",
} as Playlist;

const M3U = "#EXTM3U\n#EXTINF:-1,One\nhttp://iptv.example/1.ts\n";

beforeEach(() => {
  vi.restoreAllMocks();
  search = new URLSearchParams();
});

describe("imported playlist name", () => {
  it("reads the name the text gives itself", () => {
    expect(embeddedPlaylistName("#EXTM3U\n#PLAYLIST:My TV\n#EXTINF:-1,A\nhttp://a")).toBe("My TV");
    expect(embeddedPlaylistName('#EXTM3U x-tvg-name="Header name"\n')).toBe("Header name");
    expect(embeddedPlaylistName(M3U)).toBeNull();
  });

  it("falls back to the file name, then to 'Playlist <date>'", () => {
    const now = new Date("2026-11-21T12:00:00Z");
    expect(importedPlaylistName({ typed: " Mine ", content: "#PLAYLIST:Inner", fileName: "f.m3u", now })).toBe("Mine");
    expect(importedPlaylistName({ content: "#EXTM3U\n#PLAYLIST:Inner\n", fileName: "f.m3u", now })).toBe("Inner");
    expect(importedPlaylistName({ content: M3U, fileName: "Home TV.m3u8", now })).toBe("Home TV");
    expect(importedPlaylistName({ content: M3U, now })).toMatch(/^Playlist \S.*2026$/);
  });
});

describe("ImportPlaylistDialog", () => {
  it("imports pasted text, named after the date when it has no name", async () => {
    const imp = vi.spyOn(api.playlists, "import").mockResolvedValue(PLAYLIST);
    const onOpenChange = vi.fn();
    renderWithProviders(<ImportPlaylistDialog open onOpenChange={onOpenChange} />);
    await userEvent.click(screen.getByRole("tab", { name: /Paste text/ }));
    const submit = screen.getByRole("button", { name: "Import" });
    expect(submit).toBeDisabled();
    fireEvent.change(screen.getByLabelText("Playlist text"), { target: { value: M3U } });
    await userEvent.click(submit);
    await waitFor(() => expect(imp).toHaveBeenCalledWith({ content: M3U, name: expect.stringMatching(/^Playlist /) }));
    await waitFor(() => expect(onOpenChange).toHaveBeenCalledWith(false));
  });

  it("keeps the #PLAYLIST name of an imported file instead of the file name", async () => {
    const imp = vi.spyOn(api.playlists, "import").mockResolvedValue(PLAYLIST);
    const { container } = renderWithProviders(<ImportPlaylistDialog open onOpenChange={vi.fn()} />);
    await userEvent.click(screen.getByRole("tab", { name: /From file/ }));
    const input = (container.ownerDocument.querySelector('input[type="file"]') as HTMLInputElement)!;
    const content = "#EXTM3U\n#PLAYLIST:Sports\n#EXTINF:-1,A\nhttp://a.example/1.ts\n";
    await userEvent.upload(input, new File([content], "list.m3u", { type: "audio/x-mpegurl" }));
    await userEvent.click(screen.getByRole("button", { name: "Import" }));
    await waitFor(() => expect(imp).toHaveBeenCalledWith({ content, name: "Sports" }));
  });
});

describe("Playlist view with a bad id", () => {
  it("shows the not-found state instead of an endless '…'", async () => {
    search = new URLSearchParams("id=nope");
    const notFound = new ApiError(404, "Playlist not found", "playlist_not_found");
    vi.spyOn(api.playlists, "get").mockRejectedValue(notFound);
    vi.spyOn(api.playlists, "channels").mockRejectedValue(notFound);
    renderWithProviders(<PlaylistViewPage />);
    expect(await screen.findByText("Playlist not found")).toBeInTheDocument();
    expect(screen.queryByText("…")).toBeNull();
    expect(screen.queryByRole("searchbox")).toBeNull();
    expect(screen.getByRole("button", { name: "Playlists" })).toHaveAttribute("href", expect.stringMatching(/^\/playlists\/?$/));
  });
});
