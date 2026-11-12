import { act, fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { RECONNECT_GRACE_MS, RemoteView } from "@/components/browser/remote-view";

function setup() {
  const send = vi.fn().mockReturnValue(true);
  const onSink = vi.fn();
  render(<RemoteView page={{ width: 390, height: 844 }} hasFrame closed={false} send={send} onSink={onSink} />);
  const canvas = screen.getByTestId("remote-canvas");
  // element is 195x422 → scale 0.5
  canvas.getBoundingClientRect = () =>
    ({ left: 0, top: 0, width: 195, height: 422, right: 195, bottom: 422, x: 0, y: 0, toJSON: () => ({}) }) as DOMRect;
  return { send, onSink, canvas };
}

describe("RemoteView", () => {
  it("registers a frame sink", () => {
    const { onSink } = setup();
    expect(onSink).toHaveBeenCalledWith(expect.any(Function));
  });

  it("maps a touch tap to page coordinates", () => {
    const { send, canvas } = setup();
    fireEvent.pointerDown(canvas, { pointerId: 1, pointerType: "touch", clientX: 50, clientY: 100 });
    fireEvent.pointerUp(canvas, { pointerId: 1, pointerType: "touch", clientX: 51, clientY: 101 });
    expect(send).toHaveBeenCalledWith({ type: "tap", x: 102, y: 202 });
  });

  it("sends mouse clicks with the button", () => {
    const { send, canvas } = setup();
    fireEvent.pointerDown(canvas, { pointerId: 2, pointerType: "mouse", button: 0, clientX: 10, clientY: 10 });
    fireEvent.pointerUp(canvas, { pointerId: 2, pointerType: "mouse", button: 0, clientX: 10, clientY: 10 });
    expect(send).toHaveBeenCalledWith({ type: "click", x: 20, y: 20, button: "left" });
  });

  it("turns a drag into scroll (content follows the finger)", () => {
    const { send, canvas } = setup();
    fireEvent.pointerDown(canvas, { pointerId: 3, pointerType: "touch", clientX: 100, clientY: 300 });
    fireEvent.pointerMove(canvas, { pointerId: 3, pointerType: "touch", clientX: 100, clientY: 250 });
    fireEvent.pointerUp(canvas, { pointerId: 3, pointerType: "touch", clientX: 100, clientY: 250 });
    expect(send).toHaveBeenCalledWith({ type: "scroll", x: 200, y: 600, dx: 0, dy: 100 });
    expect(send).not.toHaveBeenCalledWith(expect.objectContaining({ type: "tap" }));
  });

  it("forwards keys and printable characters", () => {
    const { send, canvas } = setup();
    fireEvent.keyDown(canvas, { key: "Enter" });
    fireEvent.keyDown(canvas, { key: "a" });
    fireEvent.keyDown(canvas, { key: "c", metaKey: true });
    expect(send.mock.calls.map((c) => c[0])).toEqual([
      { type: "key", key: "Enter" },
      { type: "text", text: "a" },
    ]);
  });
});

describe("RemoteView connection feedback", () => {
  const base = { page: { width: 390, height: 844 }, hasFrame: true, send: vi.fn(), onSink: vi.fn() };

  it("shows a reconnecting overlay only after a grace period", () => {
    vi.useFakeTimers();
    try {
      render(<RemoteView {...base} closed={false} status="connecting" />);
      expect(screen.queryByText(/Reconnecting/)).not.toBeInTheDocument();
      act(() => vi.advanceTimersByTime(RECONNECT_GRACE_MS + 10));
      expect(screen.getByText(/Reconnecting/)).toBeInTheDocument();
    } finally {
      vi.useRealTimers();
    }
  });

  it("offers a retry once the socket gave up", () => {
    const onRetry = vi.fn();
    render(<RemoteView {...base} closed={false} status="failed" onRetry={onRetry} />);
    fireEvent.click(screen.getByRole("button", { name: /Retry/ }));
    expect(onRetry).toHaveBeenCalled();
  });

  it("offers to reopen the page when the session closed", () => {
    const onReopen = vi.fn();
    render(<RemoteView {...base} closed status="closed" onReopen={onReopen} />);
    expect(screen.getByText("Session closed")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /Reopen this page/ }));
    expect(onReopen).toHaveBeenCalled();
  });
});
