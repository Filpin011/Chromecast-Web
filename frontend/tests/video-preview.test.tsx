import { act, fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { VideoPreview } from "@/components/media/video-preview";

describe("VideoPreview", () => {
  it("replaces the player (and its native controls) with the error message and can retry", async () => {
    vi.useFakeTimers();
    try {
      render(<VideoPreview src="http://cdn.example/clip.mp4" mimeType="video/mp4" controls />);
      const video = screen.getByTestId("video-preview") as HTMLVideoElement;
      act(() => vi.runOnlyPendingTimers());
      expect(video.controls).toBe(true);
      const load = vi.spyOn(video, "load").mockImplementation(() => {});

      fireEvent.error(video);
      const alert = screen.getByRole("alert");
      expect(alert).toHaveTextContent("Anteprima non disponibile");
      expect(video.controls).toBe(false);
      expect(video.className).toContain("invisible");

      fireEvent.click(screen.getByRole("button", { name: /Riprova/ }));
      act(() => vi.runOnlyPendingTimers());
      expect(load).toHaveBeenCalled(); // old source torn down
      expect(video.getAttribute("src")).toBe("http://cdn.example/clip.mp4");
      expect(screen.queryByRole("alert")).not.toBeInTheDocument();
      expect(video.controls).toBe(true);
      fireEvent.playing(video);
      expect(video.className).not.toContain("invisible");
    } finally {
      vi.useRealTimers();
    }
  });

  it("offers no retry for formats the browser can't preview", () => {
    vi.useFakeTimers();
    try {
      render(<VideoPreview src="http://cdn.example/live.mpd" controls />);
      act(() => vi.runOnlyPendingTimers());
      expect(screen.getByRole("alert")).toHaveTextContent("non disponibile per questo formato");
      expect(screen.queryByRole("button", { name: /Riprova/ })).not.toBeInTheDocument();
      expect((screen.getByTestId("video-preview") as HTMLVideoElement).controls).toBe(false);
    } finally {
      vi.useRealTimers();
    }
  });
});
