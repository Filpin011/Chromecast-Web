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

import CastPage from "@/app/page";
import PlaylistsPage from "@/app/playlists/page";
import SettingsPage from "@/app/settings/page";
import { MediaActions } from "@/components/cast/media-actions";
import { PageHeader } from "@/components/common/page-header";
import { NowPlayingContent } from "@/components/player/now-playing";
import { api } from "@/lib/api";
import { makeDevice, makePlayer } from "./fixtures";
import { renderWithProviders } from "./render";

describe("MediaActions on narrow cards", () => {
  it("lets the primary column shrink and truncate instead of pushing icon buttons out", () => {
    renderWithProviders(<MediaActions onCast={vi.fn()} onQueue={vi.fn()} onFavorite={vi.fn()} onOpenBrowser={vi.fn()} />);
    const cast = screen.getByRole("button", { name: "Cast now" });
    const row = cast.parentElement!;
    expect(row.className).toContain("grid-cols-[minmax(0,1fr)_auto_auto_auto]");
    expect(row.className).not.toMatch(/grid-cols-\[1fr/);
    expect(cast.className).toMatch(/\bmin-w-0\b/);
    expect(cast.querySelector(".truncate")).not.toBeNull();
    for (const name of ["Add to queue", "Add to favorites", "Open in browser"]) {
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
    expect(screen.getByRole("button", { name: /Actions for/ })).toBeInTheDocument();
    // only the host truncates; the "updated" time keeps its width
    const host = screen.getByTestId("playlist-source");
    const updated = screen.getByTestId("playlist-updated");
    expect(host.className).toMatch(/\btruncate\b/);
    expect(host.className).toMatch(/\bmin-w-0\b/);
    expect(updated.className).toMatch(/\bshrink-0\b/);
    expect(updated.className).not.toMatch(/\btruncate\b/);
    expect(updated.textContent).toMatch(/updated/);
    expect(host.parentElement!.className).not.toMatch(/\btruncate\b/);
  });
});

describe("Page header on 360px phones", () => {
  it("wraps the subtitle instead of truncating it", () => {
    renderWithProviders(<PageHeader title="Cast" subtitle="Cast anything to your Chromecast" />);
    const sub = screen.getByText("Cast anything to your Chromecast");
    expect(sub.className).not.toMatch(/\btruncate\b/);
  });
});

describe("Home section links", () => {
  it("gives 'See all' a 44px touch target", async () => {
    vi.spyOn(api.history, "list").mockResolvedValue([
      { id: "h1", title: "Video", input: "https://a.example/v.mp4", source_kind: "direct", thumbnail: null, device_id: null, played_at: "2026-11-12T10:00:00Z" },
    ] as never);
    vi.spyOn(api.favorites, "list").mockResolvedValue([] as never);
    renderWithProviders(<CastPage />);
    const link = await screen.findByRole("link", { name: "See all" });
    expect(link.className).toMatch(/\bmin-h-11\b/);
  });
});

describe("Now Playing transport row on 360px phones", () => {
  const renderNowPlaying = (player: Parameters<typeof makePlayer>[0]) =>
    renderWithProviders(<NowPlayingContent device={makeDevice()} player={makePlayer(player)} receivedAt={Date.now()} />);

  it("drops the ±10 s pair below 384px of row width so Previous / Next stay on screen", () => {
    renderNowPlaying({ stream_type: "BUFFERED", duration: 600, queue: [] });
    const row = screen.getByTestId("transport-row");
    // the row is the container the buttons query (a 360px phone gives it only 320px)
    expect(row.className).toMatch(/(^|\s)@container\/transport(\s|$)/);
    expect(row.className).not.toMatch(/\boverflow-x-auto\b/);
    for (const name of ["Back 10 seconds", "Forward 10 seconds"]) {
      const btn = screen.getByRole("button", { name, hidden: true });
      expect(row.contains(btn)).toBe(true);
      expect(btn.className).toMatch(/(^|\s)hidden(\s|$)/);
      expect(btn.className).toContain("@min-[384px]/transport:inline-flex");
      // the base Button's inline-flex must not survive the merge, or the button would always show
      expect(btn.className).not.toMatch(/(^|\s)inline-flex(\s|$)/);
    }
    for (const name of ["Previous", "Next", "Back 30 seconds", "Forward 30 seconds", "Pause"]) {
      const btn = screen.getByRole("button", { name });
      expect(row.contains(btn)).toBe(true);
      expect(btn.className).not.toMatch(/(^|\s)hidden(\s|$)/);
    }
  });

  it("keeps the 10 s live skips (the only ones) always visible", () => {
    renderNowPlaying({ stream_type: "LIVE", duration: null });
    for (const name of ["Back 10 seconds", "Forward 10 seconds"]) {
      expect(screen.getByRole("button", { name }).className).not.toMatch(/(^|\s)hidden(\s|$)/);
    }
  });
});

describe("Settings idle image URL", () => {
  it("explains 'empty = default' in a description line, not in a placeholder that gets clipped", async () => {
    vi.spyOn(api.settings, "get").mockResolvedValue({
      idle_image_url: null,
      show_idle_on_connect: true,
      show_idle_on_stop: true,
      default_device_id: null,
      public_base_url: null,
      force_proxy: false,
      adblock_enabled: true,
      adblock_disabled_hosts: [],
      popup_policy: "ask",
      popup_blocked_hosts: [],
    });
    vi.spyOn(api.system, "health").mockResolvedValue({ ok: true } as never);
    vi.spyOn(api.filters, "list").mockResolvedValue([] as never);
    renderWithProviders(<SettingsPage />);
    const input = await screen.findByLabelText("Image URL");
    expect(input).toHaveAttribute("placeholder", "https://…");
    expect(input).toHaveAccessibleDescription("Leave empty to use the default image.");
  });
});
