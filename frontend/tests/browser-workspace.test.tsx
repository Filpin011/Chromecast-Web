import { fireEvent, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("sonner", () => {
  const toast = Object.assign(vi.fn(), { error: vi.fn(), success: vi.fn(), loading: vi.fn() });
  return { toast };
});
vi.mock("next/navigation", () => ({
  usePathname: () => "/browser/",
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
  useSearchParams: () => new URLSearchParams(),
}));
// no real socket in tests: a stub that never opens
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

import { BrowserWorkspace, type BrowserWorkspaceProps } from "@/components/browser/browser-workspace";
import { api } from "@/lib/api";
import type { BrowserSession } from "@/lib/api/types";
import { useUiStore } from "@/stores/ui-store";
import { renderWithProviders } from "./render";

const session: BrowserSession = {
  id: "b1",
  url: "https://site.example.com/watch/42",
  title: "Partita",
  viewport: { width: 390, height: 655 },
  captured: [],
  created_at: "2026-11-12T10:00:00Z",
  adblock_enabled: true,
  blocked_count: 0,
  pending_popups: [],
};
const other: BrowserSession = { ...session, id: "b2", url: "https://other.example.com/", title: "More" };

function setup(over: Partial<BrowserWorkspaceProps> = {}) {
  const props: BrowserWorkspaceProps = {
    session,
    sessions: [session, other],
    homeUrl: "https://site.example.com/",
    onNewSession: vi.fn(),
    onSwitchSession: vi.fn(),
    onCloseSession: vi.fn(),
    onClose: vi.fn(),
    onReopen: vi.fn(),
    ...over,
  };
  const r = renderWithProviders(<BrowserWorkspace {...props} />);
  return { ...r, props };
}

beforeEach(() => {
  vi.restoreAllMocks();
  useUiStore.setState({ immersive: false });
});

describe("BrowserWorkspace controls", () => {
  it("goes immersive while mounted (shell hides its tab bar)", () => {
    const { unmount } = setup();
    expect(useUiStore.getState().immersive).toBe(true);
    unmount();
    expect(useUiStore.getState().immersive).toBe(false);
  });

  it("Home loads the session's start page in the remote browser", async () => {
    const nav = vi.spyOn(api.browser, "navigate").mockResolvedValue(session);
    setup();
    fireEvent.click(screen.getByRole("button", { name: "Home page" }));
    await waitFor(() => expect(nav).toHaveBeenCalledWith("b1", { url: "https://site.example.com/" }));
  });

  it("reload sits in the URL pill and uses the API", async () => {
    const nav = vi.spyOn(api.browser, "navigate").mockResolvedValue(session);
    setup();
    fireEvent.click(screen.getByRole("button", { name: "Reload" }));
    await waitFor(() => expect(nav).toHaveBeenCalledWith("b1", { action: "reload" }));
  });

  it("keeps the host readable on narrow phones: the pill's reload moves to the More menu below 400px", async () => {
    const nav = vi.spyOn(api.browser, "navigate").mockResolvedValue(session);
    setup();
    const pillReload = screen.getByRole("button", { name: "Reload" });
    expect(pillReload).toHaveClass("hidden", "min-[400px]:grid");
    fireEvent.click(screen.getByRole("button", { name: "More" }));
    const item = await screen.findByRole("menuitem", { name: "Reload" });
    expect(item).toHaveClass("min-[400px]:hidden");
    fireEvent.click(item);
    await waitFor(() => expect(nav).toHaveBeenCalledWith("b1", { action: "reload" }));
  });

  it("'+' starts a new session; the tabs button lists sessions to switch to", async () => {
    const { props } = setup();
    fireEvent.click(screen.getByRole("button", { name: "New session" }));
    expect(props.onNewSession).toHaveBeenCalledTimes(1);
    expect(props.onSwitchSession).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole("button", { name: "2 open sessions" }));
    const list = await screen.findByRole("list", { name: "Open sessions" });
    expect(list).toHaveTextContent("More");
    fireEvent.click(screen.getByText("More"));
    expect(props.onSwitchSession).toHaveBeenCalledWith(other);
  });

  it("the menu opens app navigation", async () => {
    setup();
    fireEvent.click(screen.getByRole("button", { name: "Menu" }));
    const nav = await screen.findByRole("navigation", { name: "App menu" });
    expect(nav).toHaveTextContent("Library");
    expect(nav).toHaveTextContent("Settings");
  });

  it("has a keyboard toggle in the toolbar", () => {
    setup();
    expect(screen.queryByLabelText("Text to send to the page")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Keyboard" }));
    expect(screen.getByLabelText("Text to send to the page")).toBeInTheDocument();
  });

  it("overlays the keyboard bar on the page instead of shrinking the fitted viewport", () => {
    setup();
    const canvas = screen.getByTestId("remote-canvas");
    const pageArea = canvas.closest(".flex-col") as HTMLElement;
    const before = pageArea.className;
    fireEvent.click(screen.getByRole("button", { name: "Keyboard" }));
    const bar = screen.getByLabelText("Text to send to the page").closest("form")!;
    // positioned inside the page area (same box as the canvas), not a new row of the column layout
    expect(pageArea).toContainElement(bar);
    expect(bar.className).toMatch(/\babsolute\b/);
    expect(bar.className).toMatch(/\bbottom-0\b/);
    expect(pageArea.className).toBe(before);
    expect(screen.getByRole("navigation", { name: "Browser navigation" })).not.toContainElement(bar);
  });

  it("top bar controls, including the quick close, are full-size touch targets", () => {
    const { props } = setup();
    for (const name of ["Menu", "Reload", "Close the session now"]) {
      const btn = screen.getByRole("button", { name });
      expect(btn.className).toMatch(/size-11/);
    }
    fireEvent.click(screen.getByRole("button", { name: "Close the session now" }));
    expect(props.onClose).toHaveBeenCalled();
  });

  it("keeps the 'Fit to screen' pill on one line (Italian label is long) and inside the page", async () => {
    // a 320×900 phone vs the session's 390×655 viewport: the pill is offered
    vi.spyOn(window, "innerWidth", "get").mockReturnValue(320);
    vi.spyOn(window, "innerHeight", "get").mockReturnValue(900);
    const { props } = setup();
    const pill = await screen.findByRole("button", { name: "Fit to screen" });
    // absolute + centred with -translate-x-1/2: without nowrap its width is capped at half the container
    expect(pill.className).toMatch(/\bwhitespace-nowrap\b/);
    expect(pill.className).toContain("max-w-[calc(100%-1rem)]");
    expect(pill.querySelector(".truncate")).toHaveTextContent("Fit to screen");
    fireEvent.click(pill);
    expect(props.onReopen).toHaveBeenCalledWith("mobile", session.url);
  });
});
