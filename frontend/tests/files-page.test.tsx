import { fireEvent, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("sonner", () => {
  const toast = Object.assign(vi.fn(), { error: vi.fn(), success: vi.fn(), loading: vi.fn() });
  return { toast };
});
vi.mock("next/navigation", () => ({
  usePathname: () => "/files/",
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
  useSearchParams: () => new URLSearchParams(),
}));

import FilesPage from "@/app/files/page";
import { api } from "@/lib/api";
import { stripExtension } from "@/lib/format";
import { useAppStore } from "@/stores/app-store";
import { useLocalPlayerStore } from "@/stores/local-player-store";
import { makeAppState, makePlayer } from "./fixtures";
import { renderWithProviders } from "./render";

beforeEach(() => {
  vi.restoreAllMocks();
  useAppStore.getState().reset();
  useAppStore.getState().applySnapshot(makeAppState());
  useLocalPlayerStore.setState({ media: null });
  vi.spyOn(api.local, "list").mockResolvedValue({
    path: "",
    entries: [
      { name: "Clips", path: "Clips", is_dir: true, size: null, mime_type: null },
      { name: "Test Clip.mp4", path: "Test Clip.mp4", is_dir: false, size: 1024, mime_type: "video/mp4" },
    ],
  });
});

describe("stripExtension", () => {
  it("drops only a real extension", () => {
    expect(stripExtension("Test Clip.mp4")).toBe("Test Clip");
    expect(stripExtension("show.s01e01.mkv")).toBe("show.s01e01");
    expect(stripExtension(".hidden")).toBe(".hidden");
    expect(stripExtension("README")).toBe("README");
    expect(stripExtension("trailing.")).toBe("trailing.");
  });
});

describe("Files page", () => {
  it("casts a file with its name minus the extension as the title", async () => {
    const play = vi.spyOn(api.player, "play").mockResolvedValue(makePlayer());
    renderWithProviders(<FilesPage />);
    fireEvent.click(await screen.findByRole("button", { name: "Cast Test Clip.mp4" }));
    await waitFor(() =>
      expect(play).toHaveBeenCalledWith(expect.any(String), expect.objectContaining({ input: "Test Clip.mp4", kind: "local", title: "Test Clip" })),
    );
  });

  it("offers queue, favorite and 'Watch here' for files, not for folders", async () => {
    const addFav = vi.spyOn(api.favorites, "add").mockResolvedValue({} as never);
    renderWithProviders(<FilesPage />);
    await screen.findByRole("button", { name: "Cast Test Clip.mp4" });
    expect(screen.queryByRole("button", { name: "Actions for Clips" })).toBeNull();

    await userEvent.click(screen.getByRole("button", { name: "Actions for Test Clip.mp4" }));
    await userEvent.click(await screen.findByRole("menuitem", { name: "Add to favorites" }));
    await waitFor(() =>
      expect(addFav).toHaveBeenCalledWith({ title: "Test Clip", input: "Test Clip.mp4", source_kind: "local", thumbnail: null }),
    );

    await userEvent.click(screen.getByRole("button", { name: "Actions for Test Clip.mp4" }));
    await userEvent.click(await screen.findByRole("menuitem", { name: "Watch here" }));
    const media = useLocalPlayerStore.getState().media;
    expect(media?.title).toBe("Test Clip");
    expect(typeof media?.source).toBe("function");
    expect(media?.onCast).toBeTypeOf("function");
  });
});
