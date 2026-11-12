import { fireEvent, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

vi.mock("sonner", () => {
  const toast = Object.assign(vi.fn(), { error: vi.fn(), success: vi.fn(), loading: vi.fn() });
  return { toast };
});

import { QueueList, reconcileOrder } from "@/components/player/queue-list";
import { api } from "@/lib/api";
import type { QueueItem } from "@/lib/api/types";
import { makePlayer } from "./fixtures";
import { renderWithProviders } from "./render";

const item = (id: string): QueueItem => ({ id, input: `http://x/${id}`, title: `Titolo ${id}`, thumbnail: null });

describe("reconcileOrder", () => {
  it("follows the live queue when there is no local drag order", () => {
    const q = [item("a"), item("b")];
    expect(reconcileOrder(null, q)).toEqual(q);
  });

  it("keeps the dragged order but drops removed items and appends new ones", () => {
    const [a, b, c] = [item("a"), item("b"), item("c")];
    // local drag: c, a, b — meanwhile another phone removed "a" and added "d"
    const live = [b, c, item("d")];
    const out = reconcileOrder([c, a, b], live);
    expect(out.map((i) => i.id)).toEqual(["c", "b", "d"]);
    // the dragged row keeps its identity (Reorder tracks it by reference)
    expect(out[0]).toBe(c);
  });

  it("returns only the live items when the queue advanced past all of them", () => {
    expect(reconcileOrder([item("a"), item("b")], [])).toEqual([]);
  });
});

describe("QueueList", () => {
  it("renders the live queue and removes an item", async () => {
    const remove = vi.spyOn(api.player, "removeFromQueue").mockResolvedValue(makePlayer());
    renderWithProviders(<QueueList deviceId="dev-1" queue={[item("a"), item("b")]} />);
    expect(screen.getByText("Titolo a")).toBeInTheDocument();
    expect(screen.getByText("#2")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Rimuovi Titolo a" }));
    await waitFor(() => expect(remove).toHaveBeenCalledWith("dev-1", "a"));
  });

  it("shows queue changes from other clients", () => {
    const { rerender } = renderWithProviders(<QueueList deviceId="dev-1" queue={[item("a")]} />);
    rerender(<QueueList deviceId="dev-1" queue={[item("a"), item("z")]} />);
    expect(screen.getByText("Titolo z")).toBeInTheDocument();
  });
});
