import { describe, expect, it } from "vitest";
import { clientToPage, containBox, deltaToPage, toPlaywrightKey } from "@/lib/coords";

describe("containBox", () => {
  it("letterboxes a tall page in a wide box", () => {
    const b = containBox({ width: 800, height: 422 }, { width: 390, height: 844 });
    expect(b.scale).toBeCloseTo(0.5);
    expect(b.width).toBeCloseTo(195);
    expect(b.offsetX).toBeCloseTo(302.5);
    expect(b.offsetY).toBeCloseTo(0);
  });
  it("handles empty sizes", () => {
    expect(containBox({ width: 0, height: 0 }, { width: 1, height: 1 }).width).toBe(0);
  });
});

describe("clientToPage", () => {
  const page = { width: 1280, height: 720 };
  const rect = { left: 10, top: 100, width: 640, height: 640 }; // pillar: drawn 640x360 at y offset 140

  it("maps element points to page CSS pixels", () => {
    expect(clientToPage(10, 240, rect, page)).toEqual({ x: 0, y: 0 });
    expect(clientToPage(330, 420, rect, page)).toEqual({ x: 640, y: 360 });
    expect(clientToPage(650, 600, rect, page)).toEqual({ x: 1280, y: 720 });
  });

  it("returns null in the letterbox unless clamped", () => {
    expect(clientToPage(100, 150, rect, page)).toBeNull();
    expect(clientToPage(100, 150, rect, page, { clamp: true })).toEqual({ x: 180, y: 0 });
  });

  it("works at 1:1 and when upscaled", () => {
    expect(clientToPage(195, 422, { left: 0, top: 0, width: 390, height: 844 }, { width: 390, height: 844 })).toEqual({ x: 195, y: 422 });
    expect(clientToPage(100, 100, { left: 0, top: 0, width: 780, height: 1688 }, { width: 390, height: 844 })).toEqual({ x: 50, y: 50 });
  });
});

describe("deltaToPage", () => {
  it("scales drag deltas by the inverse of the fit scale", () => {
    expect(deltaToPage(10, -20, { width: 195, height: 422 }, { width: 390, height: 844 })).toEqual({ dx: 20, dy: -40 });
  });
});

describe("toPlaywrightKey", () => {
  it("maps special keys and leaves printable ones as text", () => {
    expect(toPlaywrightKey("Enter")).toBe("Enter");
    expect(toPlaywrightKey("ArrowDown")).toBe("ArrowDown");
    expect(toPlaywrightKey("F5")).toBe("F5");
    expect(toPlaywrightKey("a")).toBeNull();
  });
});
