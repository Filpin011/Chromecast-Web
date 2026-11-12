import { afterEach, describe, expect, it, vi } from "vitest";
import { createCanvasSink } from "@/hooks/use-browser-session";

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

function stubCanvas() {
  const drawImage = vi.fn();
  vi.spyOn(HTMLCanvasElement.prototype, "getContext").mockReturnValue({ drawImage } as unknown as CanvasRenderingContext2D);
  vi.spyOn(HTMLCanvasElement.prototype, "toDataURL").mockReturnValue("data:image/jpeg;base64,AAA");
  return drawImage;
}

describe("createCanvasSink.snapshot", () => {
  it("returns nothing until a frame has actually been drawn (a fresh canvas is 300px wide but blank)", async () => {
    stubCanvas();
    const bmp = { width: 390, height: 655, close: vi.fn() };
    vi.stubGlobal("createImageBitmap", vi.fn().mockResolvedValue(bmp));
    const canvas = document.createElement("canvas");
    expect(canvas.width).toBe(300);
    const sink = createCanvasSink(canvas);
    expect(sink.snapshot()).toBeNull();

    sink(btoa("jpeg"), 390, 655);
    await vi.waitFor(() => expect(canvas.width).toBe(390));
    await vi.waitFor(() => expect(sink.snapshot()).toBe("data:image/jpeg;base64,AAA"));
  });

  it("stays empty when the frame could not be decoded", async () => {
    stubCanvas();
    const decode = vi.fn().mockRejectedValue(new Error("corrupt"));
    vi.stubGlobal("createImageBitmap", decode);
    const sink = createCanvasSink(document.createElement("canvas"));
    sink(btoa("bad"), 390, 655);
    await vi.waitFor(() => expect(decode).toHaveBeenCalled());
    await Promise.resolve();
    expect(sink.snapshot()).toBeNull();
  });
});
