/**
 * jsdom has no layout engine, so these pin the CSS contracts that keep rows inside 360px phones
 * (measured with Playwright: a plain `1fr` / implicit grid track never shrinks below the
 * min-content width of nowrap text and pushes buttons off the card / screen).
 */
import { screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

vi.mock("sonner", () => {
  const toast = Object.assign(vi.fn(), { error: vi.fn(), success: vi.fn(), loading: vi.fn() });
  return { toast };
});
vi.mock("next/navigation", () => ({
  usePathname: () => "/playlists/",
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
  useSearchParams: () => new URLSearchParams(),
}));

import PlaylistsPage from "@/app/playlists/page";
import { MediaActions } from "@/components/cast/media-actions";
import { api } from "@/lib/api";
import { renderWithProviders } from "./render";

describe("MediaActions on narrow cards", () => {
  it("lets the primary column shrink and truncate instead of pushing icon buttons out", () => {
    renderWithProviders(<MediaActions onCast={vi.fn()} onQueue={vi.fn()} onFavorite={vi.fn()} onOpenBrowser={vi.fn()} />);
    const cast = screen.getByRole("button", { name: "Trasmetti ora" });
    const row = cast.parentElement!;
    expect(row.className).toContain("grid-cols-[minmax(0,1fr)_auto_auto_auto]");
    expect(row.className).not.toMatch(/grid-cols-\[1fr/);
    expect(cast.className).toMatch(/\bmin-w-0\b/);
    expect(cast.querySelector(".truncate")).not.toBeNull();
    for (const name of ["Aggiungi alla coda", "Aggiungi ai preferiti", "Apri nel browser"]) {
      expect(screen.getByRole("button", { name })).toBeInTheDocument();
    }
  });
});

describe("Playlists grid on narrow phones", () => {
  it("uses shrinkable tracks and items so long subtitles truncate", async () => {
    vi.spyOn(api.playlists, "list").mockResolvedValue([
      {
        id: "p1",
        name: "Lista con un nome lunghissimo per il test",
        source_url: "http://provider-iptv-con-un-hostname-davvero-lungo.example.com:8766/get.php",
        channel_count: 1234,
        groups: ["A", "B"],
        created_at: "2026-11-12T10:00:00Z",
        updated_at: "2026-11-12T10:00:00Z",
      },
    ]);
    renderWithProviders(<PlaylistsPage />);
    const grid = await screen.findByTestId("playlist-grid");
    expect(grid.className).toContain("grid-cols-[minmax(0,1fr)]");
    const li = grid.querySelector("li")!;
    expect(li.className).toMatch(/\bmin-w-0\b/);
    expect(screen.getByRole("button", { name: /Azioni per/ })).toBeInTheDocument();
  });
});
