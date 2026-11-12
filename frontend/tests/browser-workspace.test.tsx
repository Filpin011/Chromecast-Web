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
const other: BrowserSession = { ...session, id: "b2", url: "https://other.example.com/", title: "Altro" };

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
    fireEvent.click(screen.getByRole("button", { name: "Pagina iniziale" }));
    await waitFor(() => expect(nav).toHaveBeenCalledWith("b1", { url: "https://site.example.com/" }));
  });

  it("reload sits in the URL pill and uses the API", async () => {
    const nav = vi.spyOn(api.browser, "navigate").mockResolvedValue(session);
    setup();
    fireEvent.click(screen.getByRole("button", { name: "Ricarica" }));
    await waitFor(() => expect(nav).toHaveBeenCalledWith("b1", { action: "reload" }));
  });

  it("'+' starts a new session; the tabs button lists sessions to switch to", async () => {
    const { props } = setup();
    fireEvent.click(screen.getByRole("button", { name: "Nuova sessione" }));
    expect(props.onNewSession).toHaveBeenCalledTimes(1);
    expect(props.onSwitchSession).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole("button", { name: "2 sessioni aperte" }));
    const list = await screen.findByRole("list", { name: "Sessioni aperte" });
    expect(list).toHaveTextContent("Altro");
    fireEvent.click(screen.getByText("Altro"));
    expect(props.onSwitchSession).toHaveBeenCalledWith(other);
  });

  it("the menu opens app navigation", async () => {
    setup();
    fireEvent.click(screen.getByRole("button", { name: "Menu" }));
    const nav = await screen.findByRole("navigation", { name: "Menu app" });
    expect(nav).toHaveTextContent("Libreria");
    expect(nav).toHaveTextContent("Impostazioni");
  });

  it("has a keyboard toggle in the toolbar", () => {
    setup();
    expect(screen.queryByLabelText("Testo da inviare alla pagina")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Tastiera" }));
    expect(screen.getByLabelText("Testo da inviare alla pagina")).toBeInTheDocument();
  });

  it("overlays the keyboard bar on the page instead of shrinking the fitted viewport", () => {
    setup();
    const canvas = screen.getByTestId("remote-canvas");
    const pageArea = canvas.closest(".flex-col") as HTMLElement;
    const before = pageArea.className;
    fireEvent.click(screen.getByRole("button", { name: "Tastiera" }));
    const bar = screen.getByLabelText("Testo da inviare alla pagina").closest("form")!;
    // positioned inside the page area (same box as the canvas), not a new row of the column layout
    expect(pageArea).toContainElement(bar);
    expect(bar.className).toMatch(/\babsolute\b/);
    expect(bar.className).toMatch(/\bbottom-0\b/);
    expect(pageArea.className).toBe(before);
    expect(screen.getByRole("navigation", { name: "Navigazione browser" })).not.toContainElement(bar);
  });

  it("top bar controls, including the quick close, are full-size touch targets", () => {
    const { props } = setup();
    for (const name of ["Menu", "Ricarica", "Chiudi subito la sessione"]) {
      const btn = screen.getByRole("button", { name });
      expect(btn.className).toMatch(/size-11/);
    }
    fireEvent.click(screen.getByRole("button", { name: "Chiudi subito la sessione" }));
    expect(props.onClose).toHaveBeenCalled();
  });
});
