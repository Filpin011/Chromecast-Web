import { fireEvent, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
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
    await userEvent.click(screen.getByRole("button", { name: "Actions for Titolo a" }));
    await userEvent.click(await screen.findByRole("menuitem", { name: "Remove" }));
    await waitFor(() => expect(remove).toHaveBeenCalledWith("dev-1", "a"));
  });

  it("moves an item with the arrow keys on its focused handle, keeping the focus", async () => {
    const reorder = vi.spyOn(api.player, "reorderQueue").mockResolvedValue(makePlayer());
    renderWithProviders(<QueueList deviceId="dev-1" queue={[item("a"), item("b"), item("c")]} />);
    const handle = screen.getByRole("button", { name: "Drag Titolo a" });
    expect(handle).toHaveAccessibleDescription(/arrow keys/);
    handle.focus();
    fireEvent.keyDown(handle, { key: "ArrowDown" });
    await waitFor(() => expect(reorder).toHaveBeenCalledWith("dev-1", ["b", "a", "c"]));
    expect(screen.getByRole("status")).toHaveTextContent("Titolo a moved to position 2");
    expect(screen.getByRole("button", { name: "Drag Titolo a" })).toHaveFocus();
    // ArrowUp on the first row is a no-op (the mocked server kept a, b, c)
    reorder.mockClear();
    fireEvent.keyDown(screen.getByRole("button", { name: "Drag Titolo a" }), { key: "ArrowUp" });
    expect(reorder).not.toHaveBeenCalled();
  });

  it("offers Move up / Move down in the row menu where they apply", async () => {
    const reorder = vi.spyOn(api.player, "reorderQueue").mockResolvedValue(makePlayer());
    renderWithProviders(<QueueList deviceId="dev-1" queue={[item("a"), item("b")]} />);
    await userEvent.click(screen.getByRole("button", { name: "Actions for Titolo b" }));
    expect(screen.queryByRole("menuitem", { name: "Move down" })).toBeNull();
    await userEvent.click(await screen.findByRole("menuitem", { name: "Move up" }));
    await waitFor(() => expect(reorder).toHaveBeenCalledWith("dev-1", ["b", "a"]));
  });

  it("shows queue changes from other clients", () => {
    const { rerender } = renderWithProviders(<QueueList deviceId="dev-1" queue={[item("a")]} />);
    rerender(<QueueList deviceId="dev-1" queue={[item("a"), item("z")]} />);
    expect(screen.getByText("Titolo z")).toBeInTheDocument();
  });
});
