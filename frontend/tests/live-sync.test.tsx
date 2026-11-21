import { QueryClient } from "@tanstack/react-query";
import { fireEvent, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const nav = vi.hoisted(() => ({ replace: vi.fn(), params: new URLSearchParams() }));

vi.mock("sonner", () => {
  const toast = Object.assign(vi.fn(), { error: vi.fn(), success: vi.fn(), loading: vi.fn() });
  return { toast };
});
vi.mock("next/navigation", () => ({
  usePathname: () => "/library/",
  useRouter: () => ({ push: vi.fn(), replace: nav.replace }),
  useSearchParams: () => nav.params,
}));

import LibraryPage from "@/app/library/page";
import { handleServerMessage } from "@/components/app/state-socket-bridge";
import { api } from "@/lib/api";
import type { HistoryEntry, ServerMessage } from "@/lib/api/types";
import { qk } from "@/lib/query";
import { renderWithProviders } from "./render";

function seeded(): QueryClient {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, staleTime: Infinity } } });
  client.setQueryData(qk.settings, {});
  client.setQueryData(qk.favorites, []);
  client.setQueryData([...qk.history, 100], []);
  client.setQueryData([...qk.history, 6], []);
  client.setQueryData(qk.playlists, []);
  client.setQueryData(qk.channels("p1", "", null), { items: [], total: 0 });
  client.setQueryData(qk.health, {});
  return client;
}

const stale = (client: QueryClient) =>
  client
    .getQueryCache()
    .getAll()
    .filter((q) => q.state.isInvalidated)
    .map((q) => JSON.stringify(q.queryKey))
    .sort();

describe("/ws invalidate", () => {
  it("invalidates exactly the queries behind the keys", () => {
    const client = seeded();
    handleServerMessage({ type: "invalidate", keys: ["history", "playlists"] }, client);
    expect(stale(client)).toEqual(
      [JSON.stringify(qk.channels("p1", "", null)), '["history",100]', '["history",6]', '["playlists"]'].sort(),
    );
  });

  it("covers settings and favorites, ignores unknown keys", () => {
    const client = seeded();
    handleServerMessage({ type: "invalidate", keys: ["settings", "favorites", "devices", "__proto__"] }, client);
    expect(stale(client)).toEqual(['["favorites"]', '["settings"]']);
  });

  it("ignores unknown message types and invalidates without a client", () => {
    const client = seeded();
    expect(() => handleServerMessage({ type: "brand_new", data: 1 } as unknown as ServerMessage, client)).not.toThrow();
    expect(() => handleServerMessage({ type: "invalidate", keys: ["favorites"] })).not.toThrow();
    expect(stale(client)).toEqual([]);
  });
});

const entry = (id: string, title: string): HistoryEntry => ({
  id,
  title,
  input: `https://cdn.example.com/${id}.mp4`,
  source_kind: "direct",
  thumbnail: null,
  device_id: null,
  played_at: "2026-11-20T10:00:00Z",
});

describe("history row menu", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    nav.params = new URLSearchParams("tab=history");
    vi.spyOn(api.favorites, "list").mockResolvedValue([]);
    vi.spyOn(api.local, "list").mockRejectedValue(new Error("no media root"));
  });

  it("removes a single entry", async () => {
    const list = vi.spyOn(api.history, "list").mockResolvedValue([entry("a", "Alpha"), entry("b", "Beta")]);
    const remove = vi.spyOn(api.history, "remove").mockResolvedValue(undefined);
    renderWithProviders(<LibraryPage />);

    fireEvent.click(await screen.findByRole("button", { name: "Actions for Alpha" }));
    list.mockResolvedValue([entry("b", "Beta")]);
    fireEvent.click(await screen.findByRole("menuitem", { name: "Remove from history" }));
    await waitFor(() => expect(remove).toHaveBeenCalledWith("a"));
    await waitFor(() => expect(screen.queryByText("Alpha")).not.toBeInTheDocument());
    expect(screen.getByText("Beta")).toBeInTheDocument();
  });
});
