import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { AdblockButton, blockedBadge } from "@/components/browser/adblock-button";
import { PopupPrompt } from "@/components/browser/popup-prompt";
import { Api } from "@/lib/api";

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
    await userEvent.click(screen.getByRole("button", { name: /Blocco pubblicità attivo, 12/ }));
    expect(await screen.findByText("Blocco pubblicità attivo su questo sito")).toBeInTheDocument();
    expect(screen.getByText("12 richieste bloccate su questa pagina")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Disattiva il blocco su questo sito" }));
    expect(onToggle).toHaveBeenCalledWith(false);
  });

  it("hides the badge when blocking is off for the site", () => {
    render(<AdblockButton url="https://a.example/" enabled={false} blocked={5} onToggle={vi.fn()} onStopMedia={vi.fn()} />);
    expect(screen.queryByTestId("blocked-badge")).toBeNull();
    expect(screen.getByRole("button", { name: "Blocco pubblicità disattivato" })).toBeInTheDocument();
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
    expect(screen.getByRole("alertdialog")).toHaveTextContent("La pagina vuole aprire: partner.example.org");
    expect(screen.getByText("+2")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: /Apri/ }));
    await userEvent.click(screen.getByRole("button", { name: /^Blocca$/ }));
    await userEvent.click(screen.getByRole("button", { name: /Blocca sempre per questo sito/ }));
    expect(onDecide.mock.calls.map((c) => c[0])).toEqual(["open", "block", "block_always"]);
  });
});
