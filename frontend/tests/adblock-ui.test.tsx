import { act, fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { AdblockButton, blockedBadge } from "@/components/browser/adblock-button";
import { PopupPrompt } from "@/components/browser/popup-prompt";
import { AdblockSettings } from "@/components/settings/adblock-settings";
import { useLocaleStore } from "@/i18n";
import { Api, api } from "@/lib/api";
import { renderWithProviders } from "./render";

function jsonResponse(body: unknown) {
  return new Response(JSON.stringify(body), { status: 200, headers: { "Content-Type": "application/json" } });
}

describe("ad-block API client", () => {
  it("hits the contract endpoints", async () => {
    const fetch = vi.fn().mockImplementation(() => Promise.resolve(jsonResponse({ lists: [] })));
    const api = new Api("", fetch);
    await api.browser.setAdblock("s 1", false);
    await api.browser.popupDecision("s1", "p1", "block_always");
    await api.filters.list();
    await api.filters.refresh();
    const calls = fetch.mock.calls.map(([url, init]) => [init.method, url, init.body && JSON.parse(init.body)]);
    expect(calls).toEqual([
      ["POST", "/api/browser/sessions/s%201/adblock", { enabled: false }],
      ["POST", "/api/browser/sessions/s1/popups/p1", { decision: "block_always" }],
      ["GET", "/api/filters", undefined],
      ["POST", "/api/filters/refresh", undefined],
    ]);
  });
});

describe("AdblockButton", () => {
  it("formats the badge", () => {
    expect(blockedBadge(0)).toBeNull();
    expect(blockedBadge(7)).toBe("7");
    expect(blockedBadge(250)).toBe("99+");
  });

  it("shows the blocked count and toggles the current site", async () => {
    const onToggle = vi.fn();
    const onStop = vi.fn();
    render(
      <AdblockButton url="https://www.sport.example.com/live" enabled blocked={12} onToggle={onToggle} onStopMedia={onStop} />,
    );
    expect(screen.getByTestId("blocked-badge")).toHaveTextContent("12");
    await userEvent.click(screen.getByRole("button", { name: /Ad blocking on, 12 requests blocked/ }));
    expect(await screen.findByText("Ad blocking on for this site")).toBeInTheDocument();
    expect(screen.getByText("12 requests blocked on this page")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Turn off blocking on this site" }));
    expect(onToggle).toHaveBeenCalledWith(false);
  });

  it("hides the badge when blocking is off for the site", () => {
    render(<AdblockButton url="https://a.example/" enabled={false} blocked={5} onToggle={vi.fn()} onStopMedia={vi.fn()} />);
    expect(screen.queryByTestId("blocked-badge")).toBeNull();
    expect(screen.getByRole("button", { name: "Ad blocking off" })).toBeInTheDocument();
  });
});

describe("PopupPrompt", () => {
  const popup = {
    id: "p1",
    url: "https://partner.example.org/watch?x=1",
    host: "partner.example.org",
    opener_url: "https://tv.example.com/live",
    created_at: "2026-11-12T10:00:00Z",
  };

  it("asks and reports every decision", async () => {
    const onDecide = vi.fn();
    render(<PopupPrompt popup={popup} more={2} onDecide={onDecide} />);
    expect(screen.getByRole("alertdialog")).toHaveTextContent("The page wants to open: partner.example.org");
    expect(screen.getByText("+2")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: /Open/ }));
    await userEvent.click(screen.getByRole("button", { name: /^Block$/ }));
    await userEvent.click(screen.getByRole("button", { name: /Always block for this site/ }));
    expect(onDecide.mock.calls.map((c) => c[0])).toEqual(["open", "block", "block_always"]);
  });
});

describe("AdblockSettings filter lists", () => {
  afterEach(() => {
    vi.restoreAllMocks();
    useLocaleStore.setState({ locale: "en", hydrated: false });
  });

  it("names the bundled list (updated_at null) in the UI language, keeps downloaded list names", async () => {
    vi.spyOn(api.filters, "list").mockResolvedValue({
      lists: [
        { name: "Bundled fallback", rules: 91, updated_at: null },
        { name: "EasyList", rules: 50000, updated_at: "2026-11-12T08:00:00Z" },
      ],
    });
    act(() => useLocaleStore.setState({ locale: "it", hydrated: true }));
    renderWithProviders(<AdblockSettings settings={undefined} onChange={vi.fn()} />);
    expect(await screen.findByText("Lista di riserva")).toBeInTheDocument();
    expect(screen.queryByText("Bundled fallback")).toBeNull();
    expect(screen.getByText("EasyList")).toBeInTheDocument();
  });
});
