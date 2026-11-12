/**
 * Coordinate mapping for the remote browser view.
 * The remote page (viewport W×H CSS px) is drawn "object-fit: contain" inside an element.
 * We map pointer positions in the element back to page CSS pixels.
 */

export interface Rect {
  left: number;
  top: number;
  width: number;
  height: number;
}

export interface Size {
  width: number;
  height: number;
}

export interface ContentBox {
  /** Offset of the drawn image inside the element (letterbox). */
  offsetX: number;
  offsetY: number;
  /** Drawn size in element pixels. */
  width: number;
  height: number;
  /** Element px per page px. */
  scale: number;
}

/** Geometry of a `contain`-fitted image of size `content` inside a box of size `box`. */
export function containBox(box: Size, content: Size): ContentBox {
  if (content.width <= 0 || content.height <= 0 || box.width <= 0 || box.height <= 0) {
    return { offsetX: 0, offsetY: 0, width: 0, height: 0, scale: 1 };
  }
  const scale = Math.min(box.width / content.width, box.height / content.height);
  const width = content.width * scale;
  const height = content.height * scale;
  return {
    offsetX: (box.width - width) / 2,
    offsetY: (box.height - height) / 2,
    width,
    height,
    scale,
  };
}

/**
 * Map a client (viewport) point to page coordinates.
 * Returns null when the point falls in the letterbox area outside the page.
 */
export function clientToPage(
  clientX: number,
  clientY: number,
  rect: Rect,
  page: Size,
  opts: { clamp?: boolean } = {},
): { x: number; y: number } | null {
  const box = containBox({ width: rect.width, height: rect.height }, page);
  if (box.width === 0) return null;
  const lx = clientX - rect.left - box.offsetX;
  const ly = clientY - rect.top - box.offsetY;
  let x = lx / box.scale;
  let y = ly / box.scale;
  const outside = x < 0 || y < 0 || x > page.width || y > page.height;
  if (outside && !opts.clamp) return null;
  x = Math.min(page.width, Math.max(0, x));
  y = Math.min(page.height, Math.max(0, y));
  return { x: Math.round(x), y: Math.round(y) };
}

/** Convert an on-screen drag/wheel delta (element px) into page px. */
export function deltaToPage(dx: number, dy: number, rect: Size, page: Size): { dx: number; dy: number } {
  const box = containBox(rect, page);
  if (box.width === 0) return { dx: 0, dy: 0 };
  return { dx: Math.round(dx / box.scale), dy: Math.round(dy / box.scale) };
}

/** Map a browser KeyboardEvent.key to a Playwright key name, or null if it should be sent as text. */
export function toPlaywrightKey(key: string): string | null {
  const special: Record<string, string> = {
    Enter: "Enter",
    Backspace: "Backspace",
    Tab: "Tab",
    Escape: "Escape",
    Delete: "Delete",
    ArrowUp: "ArrowUp",
    ArrowDown: "ArrowDown",
    ArrowLeft: "ArrowLeft",
    ArrowRight: "ArrowRight",
    Home: "Home",
    End: "End",
    PageUp: "PageUp",
    PageDown: "PageDown",
  };
  if (key in special) return special[key];
  if (/^F\d{1,2}$/.test(key)) return key;
  return null;
}
