import { act, screen } from "@testing-library/react";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("next/navigation", () => ({
  usePathname: () => "/",
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
  useSearchParams: () => new URLSearchParams(),
}));

import { AppShell, selectHasMiniPlayer } from "@/components/app/app-shell";
import { toasterPlacement } from "@/components/app/app-toaster";
import { initialAppData, reduceSnapshot, useAppStore } from "@/stores/app-store";
import { useUiStore } from "@/stores/ui-store";
import { makeAppState, makePlayer } from "./fixtures";
import { renderWithProviders } from "./render";

beforeEach(() => {
  useAppStore.getState().reset();
  useUiStore.setState({ immersive: false, nowPlayingOpen: false, devicePickerOpen: false });
});

describe("selectHasMiniPlayer", () => {
  it("is true for playback, the idle image or a queue; false when idle", () => {
    const at = (p = makePlayer()) => reduceSnapshot(initialAppData, makeAppState({ players: { "dev-1": p } }), 1);
    expect(selectHasMiniPlayer(at())).toBe(true);
    expect(selectHasMiniPlayer(at(makePlayer({ player_state: "IDLE" })))).toBe(false);
    expect(selectHasMiniPlayer(at(makePlayer({ player_state: "PLAYING", showing_idle_image: true })))).toBe(true);
    expect(selectHasMiniPlayer(initialAppData)).toBe(false);
  });
});

describe("AppShell", () => {
  it("flags the mini player and hides the tab bar while the remote browser is immersive", () => {
    useAppStore.getState().applySnapshot(makeAppState());
    const { container } = renderWithProviders(
      <AppShell>
        <p>contenuto</p>
      </AppShell>,
    );
    const shell = container.firstElementChild as HTMLElement;
    expect(shell.dataset.mini).toBe("on");
    expect(shell.dataset.tabbar).toBe("on");
    const navs = () => screen.queryAllByRole("navigation", { name: "Main navigation" }).length;
    const before = navs(); // sidebar + bottom tab bar

    act(() => useUiStore.getState().setImmersive(true));
    expect(shell.dataset.tabbar).toBe("off");
    expect(shell.dataset.mini).toBe("off");
    expect(navs()).toBe(before - 1);
  });
});

describe("AppShell chrome", () => {
  it("hides the connection banner while the remote browser is immersive", () => {
    vi.useFakeTimers();
    try {
      useAppStore.getState().setConnection("closed");
      renderWithProviders(
        <AppShell>
          <p>contenuto</p>
        </AppShell>,
      );
      act(() => {
        vi.advanceTimersByTime(3000);
      });
      expect(screen.getByText(/Lost connection to the server/)).toBeInTheDocument();
      act(() => useUiStore.getState().setImmersive(true));
      expect(screen.queryByText(/Lost connection to the server/)).not.toBeInTheDocument();
    } finally {
      vi.useRealTimers();
    }
  });

  it("renders the toaster inside the shell so it sees the chrome metrics", () => {
    const { container } = renderWithProviders(
      <AppShell>
        <p>contenuto</p>
      </AppShell>,
    );
    const shell = container.firstElementChild as HTMLElement;
    expect(shell.querySelector("section[aria-label^='Notifications']")).not.toBeNull();
  });
});

describe("toasterPlacement", () => {
  it("keeps toasts off the top bars on phones", () => {
    const phone = toasterPlacement(false, false);
    expect(phone.position).toBe("bottom-center");
    expect(JSON.stringify(phone.mobileOffset)).toContain("var(--tabbar-h)");
    expect(JSON.stringify(phone.mobileOffset)).toContain("var(--mini-h)");
  });

  it("puts immersive-browser toasts below the 56px top bar (the close button stays reachable)", () => {
    const p = toasterPlacement(false, true);
    expect(p.position).toBe("top-center");
    const top = (p.mobileOffset as { top: string }).top;
    expect(top).toContain("3.5rem");
    expect(top).toContain("safe-area-inset-top");
  });

  it("uses a bottom corner on desktop", () => {
    expect(toasterPlacement(true, false).position).toBe("bottom-right");
  });
});

describe("layout CSS", () => {
  // Regression: a composite var (e.g. --bottom-chrome) declared on :root resolves --mini-h on :root,
  // so the shell's [data-mini="on"] override never reached pb-chrome / h-viewport.
  const css = readFileSync(join(__dirname, "../src/app/globals.css"), "utf8");
  const utility = (name: string) => css.match(new RegExp(`@utility ${name} \\{([^}]*)\\}`))?.[1] ?? "";

  it("combines the shell metrics where they are used", () => {
    for (const name of ["pb-chrome", "h-viewport"]) {
      const body = utility(name);
      expect(body).toContain("var(--mini-h)");
      expect(body).toContain("var(--tabbar-h)");
    }
    expect(css).toMatch(/\[data-mini="on"\]\s*\{\s*--mini-h:/);
    expect(css).toMatch(/\[data-tabbar="off"\]\s*\{\s*--tabbar-h:\s*0/);
  });
});
