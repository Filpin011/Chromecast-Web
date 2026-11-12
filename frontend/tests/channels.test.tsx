import { fireEvent, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { ChannelList } from "@/components/playlists/channel-list";
import type { Channel } from "@/lib/api/types";
import { channelInput, preferredChannelLayout } from "@/lib/channels";
import { renderWithProviders } from "./render";

const ch = (i: number, over: Partial<Channel> = {}): Channel => ({
  id: `c${i}`,
  playlist_id: "p1",
  name: `IT: Rai ${i} HD`,
  url: `http://iptv/${i}.m3u8`,
  logo: null,
  group: "Italia",
  tvg_id: null,
  ...over,
});

describe("channelInput", () => {
  it("folds headers into the Kodi syntax the backend stores and replays", () => {
    expect(channelInput(ch(1))).toBe("http://iptv/1.m3u8");
    expect(channelInput(ch(1, { headers: {} }))).toBe("http://iptv/1.m3u8");
    expect(channelInput(ch(1, { headers: { Referer: "https://site/a b", "User-Agent": "VLC/3" } }))).toBe(
      "http://iptv/1.m3u8|Referer=https%3A%2F%2Fsite%2Fa%20b&User-Agent=VLC%2F3",
    );
  });
});

describe("preferredChannelLayout", () => {
  it("uses the logo grid only when most channels have a logo", () => {
    const noLogos = Array.from({ length: 12 }, (_, i) => ch(i));
    expect(preferredChannelLayout(noLogos)).toBe("list");
    const someLogos = noLogos.map((c, i) => (i < 4 ? { ...c, logo: "http://l/x.png" } : c));
    expect(preferredChannelLayout(someLogos)).toBe("list");
    expect(preferredChannelLayout(noLogos.map((c) => ({ ...c, logo: "http://l/x.png" })))).toBe("grid");
    expect(preferredChannelLayout([])).toBe("list");
  });
});

describe("ChannelList", () => {
  const items = Array.from({ length: 3 }, (_, i) => ch(i + 1));
  const renderList = (layout: "grid" | "list", onSelect = vi.fn(), onAction = vi.fn()) => {
    renderWithProviders(
      <ChannelList
        total={items.length}
        loaded={items.length}
        getItem={(i) => items[i]}
        layout={layout}
        onSelect={onSelect}
        onAction={onAction}
        onNeedMore={() => {}}
      />,
    );
    return { onSelect, onAction };
  };

  it("shows two-line names in the grid so similar channels stay distinguishable", () => {
    renderList("grid");
    const name = screen.getByText("IT: Rai 2 HD");
    expect(name.className).toContain("line-clamp-2");
    expect(name.closest("button")).toHaveAttribute("title", "IT: Rai 2 HD");
  });

  it.each(["grid", "list"] as const)("tap casts; the overflow menu queues, favorites and previews (%s)", async (layout) => {
    const { onSelect, onAction } = renderList(layout);
    fireEvent.click(screen.getByText("IT: Rai 1 HD"));
    expect(onSelect).toHaveBeenCalledWith(items[0]);

    for (const [label, action] of [
      ["Add to queue", "queue"],
      ["Add to favorites", "favorite"],
      ["Preview", "preview"],
    ] as const) {
      fireEvent.click(screen.getByRole("button", { name: "More actions for IT: Rai 2 HD" }));
      fireEvent.click(await screen.findByRole("menuitem", { name: label }));
      expect(onAction).toHaveBeenLastCalledWith(action, items[1]);
    }
    expect(onSelect).toHaveBeenCalledTimes(1);
  });

  it("opens the same menu on long-press / right-click", async () => {
    renderList("grid");
    const item = screen.getByText("IT: Rai 3 HD").closest("[role=listitem]") as HTMLElement;
    fireEvent.contextMenu(item);
    expect(await screen.findByRole("menuitem", { name: "Add to queue" })).toBeInTheDocument();
  });
});
