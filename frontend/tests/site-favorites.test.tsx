import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const nav = vi.hoisted(() => ({ push: vi.fn(), replace: vi.fn(), params: new URLSearchParams() }));

vi.mock("sonner", () => {
  const toast = Object.assign(vi.fn(), { error: vi.fn(), success: vi.fn(), loading: vi.fn() });
  return { toast };
});
vi.mock("next/navigation", () => ({
  usePathname: () => "/",
  useRouter: () => ({ push: nav.push, replace: nav.replace }),
  useSearchParams: () => nav.params,
}));
vi.mock("@/lib/ws", async (orig) => {
  const mod = await orig<typeof import("@/lib/ws")>();
  class BrowserSocket {
    gaveUp = false;
    connect() {}
    close() {}
    retry() {}
    send() {
      return false;
    }
    onStatus() {
      return () => {};
    }
    onMessage() {
      return () => {};
    }
  }
  return { ...mod, BrowserSocket };
});

import CastPage from "@/app/page";
import LibraryPage from "@/app/library/page";
import { BrowserWorkspace } from "@/components/browser/browser-workspace";
import { api } from "@/lib/api";
import type { BrowserSession, Favorite } from "@/lib/api/types";
import { renderWithProviders } from "./render";

const PAGE = "https://site.example.com/watch/42";
const session: BrowserSession = {
  id: "b1",
  url: PAGE,
  title: "Partita",
  viewport: { width: 390, height: 655 },
  captured: [],
  created_at: "2026-11-12T10:00:00Z",
  adblock_enabled: true,
  blocked_count: 0,
  pending_popups: [],
};
const site: Favorite = {
  id: "s1",
  kind: "site",
  title: "Partita",
  input: PAGE,
  source_kind: "webpage",
  thumbnail: "https://site.example.com/favicon.ico",
  created_at: "2026-11-12T10:00:00Z",
};
const mediaFav: Favorite = {
  id: "m1",
  kind: "media",
  title: "Rai 1",
  input: "https://x/rai1.m3u8",
  source_kind: "direct",
  thumbnail: null,
  created_at: "2026-11-11T10:00:00Z",
};

function workspace() {
  return renderWithProviders(
    <BrowserWorkspace
      session={session}
      sessions={[session]}
      homeUrl={PAGE}
      onNewSession={vi.fn()}
      onSwitchSession={vi.fn()}
      onCloseSession={vi.fn()}
      onClose={vi.fn()}
      onReopen={vi.fn()}
    />,
  );
}

beforeEach(() => {
  vi.restoreAllMocks();
  nav.push.mockReset();
  nav.params = new URLSearchParams();
  vi.spyOn(api.history, "list").mockResolvedValue([]);
  vi.spyOn(api.local, "list").mockRejectedValue(new Error("no media root"));
});

describe("browser star (site favorite)", () => {
  it("saves the current page, then shows filled and removes it on the next tap", async () => {
    const list = vi.spyOn(api.favorites, "list").mockResolvedValue([]);
    const add = vi.spyOn(api.browser, "favoriteSite").mockResolvedValue(site);
    const remove = vi.spyOn(api.favorites, "remove").mockResolvedValue(undefined);
    workspace();

    const star = await screen.findByRole("button", { name: "Add site to favorites" });
    expect(star).toHaveAttribute("aria-pressed", "false");
    list.mockResolvedValue([site]);
    fireEvent.click(star);
    await waitFor(() => expect(add).toHaveBeenCalledWith("b1"));

    const filled = await screen.findByRole("button", { name: "Remove site from favorites" });
    expect(filled).toHaveAttribute("aria-pressed", "true");
    list.mockResolvedValue([]);
    fireEvent.click(filled);
    await waitFor(() => expect(remove).toHaveBeenCalledWith("s1"));
    expect(await screen.findByRole("button", { name: "Add site to favorites" })).toBeInTheDocument();
    expect(add).toHaveBeenCalledTimes(1);
  });

  it("is not filled by a media favorite of the same page", async () => {
    vi.spyOn(api.favorites, "list").mockResolvedValue([{ ...mediaFav, input: PAGE, source_kind: "webpage" }]);
    workspace();
    expect(await screen.findByRole("button", { name: "Add site to favorites" })).toHaveAttribute("aria-pressed", "false");
  });
});

describe("opening a site favorite", () => {
  it("Library › Sites opens the page in the remote browser instead of casting", async () => {
    nav.params = new URLSearchParams("tab=sites");
    vi.spyOn(api.favorites, "list").mockResolvedValue([site, mediaFav]);
    const play = vi.spyOn(api.player, "play");
    renderWithProviders(<LibraryPage />);

    const row = await screen.findByRole("button", { name: "Open Partita in the browser" });
    expect(screen.queryByText("Rai 1")).not.toBeInTheDocument(); // media favorites stay in their own tab
    fireEvent.click(row);
    expect(nav.push).toHaveBeenCalledWith(`/browser/?url=${encodeURIComponent(PAGE)}`);
    expect(play).not.toHaveBeenCalled();
  });

  it("Library › Sites renames and removes a site", async () => {
    nav.params = new URLSearchParams("tab=sites");
    vi.spyOn(api.favorites, "list").mockResolvedValue([site]);
    const rename = vi.spyOn(api.favorites, "rename").mockResolvedValue({ ...site, title: "Calcio" });
    const remove = vi.spyOn(api.favorites, "remove").mockResolvedValue(undefined);
    renderWithProviders(<LibraryPage />);

    fireEvent.click(await screen.findByRole("button", { name: "Actions for Partita" }));
    fireEvent.click(await screen.findByRole("menuitem", { name: "Rename" }));
    const dialog = await screen.findByRole("dialog");
    fireEvent.change(within(dialog).getByLabelText("Name"), { target: { value: "  Calcio " } });
    fireEvent.click(within(dialog).getByRole("button", { name: "Save" }));
    await waitFor(() => expect(rename).toHaveBeenCalledWith("s1", "Calcio"));

    fireEvent.click(await screen.findByRole("button", { name: "Actions for Partita" }));
    fireEvent.click(await screen.findByRole("menuitem", { name: "Delete" }));
    await waitFor(() => expect(remove).toHaveBeenCalledWith("s1"));
  });

  it("Home shows saved sites as tiles that open the remote browser", async () => {
    vi.spyOn(api.favorites, "list").mockResolvedValue([site, mediaFav]);
    renderWithProviders(<CastPage />);
    fireEvent.click(await screen.findByRole("button", { name: "Open Partita in the browser" }));
    expect(nav.push).toHaveBeenCalledWith(`/browser/?url=${encodeURIComponent(PAGE)}`);
    expect(screen.getByText("Saved sites")).toBeInTheDocument();
    expect(screen.getByText("Rai 1")).toBeInTheDocument(); // media favorites keep their row
  });
});
