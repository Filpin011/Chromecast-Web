"use client";

import { MonitorX, RotateCw, WifiOff } from "lucide-react";
import { useEffect, useRef, useState, type PointerEvent as RPointerEvent } from "react";
import { MediaOverlay } from "@/components/common/media-overlay";
import type { BrowserClientMsg } from "@/lib/api/types";
import type { BrowserLinkStatus } from "@/lib/browser-session";
import { clientToPage, deltaToPage, toPlaywrightKey, type Size } from "@/lib/coords";
import { useT } from "@/i18n";
import { cn } from "@/lib/utils";
import { createCanvasSink, type FrameSink } from "@/hooks/use-browser-session";

const TAP_SLOP = 8;
/** Brief socket blips don't flash an overlay. */
export const RECONNECT_GRACE_MS = 1500;
const MOUSEMOVE_MS = 80;

export interface RemoteViewProps {
  page: Size | null;
  hasFrame: boolean;
  closed: boolean;
  send: (msg: BrowserClientMsg) => boolean;
  /** Receives the canvas sink (and a snapshot function) once mounted. */
  onSink: (sink: (FrameSink & { snapshot: () => string | null }) | null) => void;
  /** Viewer socket status: while not open, input can't reach the page (overlay after a grace period). */
  status?: BrowserLinkStatus;
  /** Reconnect after the socket gave up. */
  onRetry?: () => void;
  /** Open the same page again in a new session (offered once the session closed). */
  onReopen?: () => void;
  className?: string;
}

/** `value` once it has held for `ms` (false immediately when it turns false). */
function useSettled(value: boolean, ms: number): boolean {
  const [settled, setSettled] = useState(false);
  useEffect(() => {
    if (!value) return;
    const t = setTimeout(() => setSettled(true), ms);
    return () => {
      clearTimeout(t);
      setSettled(false);
    };
  }, [value, ms]);
  return value && settled;
}

interface Gesture {
  id: number;
  type: string;
  startX: number;
  startY: number;
  lastX: number;
  lastY: number;
  dragging: boolean;
  button: number;
}

/**
 * The streamed remote page. Taps/clicks/drags/wheel/keys are mapped from screen to page CSS pixels.
 * Drag = scroll (like a touch screen), short press = tap/click.
 */
export function RemoteView({ page, hasFrame, closed, send, onSink, status = "open", onRetry, onReopen, className }: RemoteViewProps) {
  const t = useT();
  const failed = !closed && status === "failed";
  const reconnecting = useSettled(!closed && !failed && status !== "open", RECONNECT_GRACE_MS);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const gesture = useRef<Gesture | null>(null);
  const lastMove = useRef(0);
  const pageRef = useRef(page);
  useEffect(() => {
    pageRef.current = page;
  }, [page]);

  useEffect(() => {
    const c = canvasRef.current;
    if (!c) return;
    onSink(createCanvasSink(c));
    return () => onSink(null);
  }, [onSink]);

  // Wheel must be non-passive to prevent the outer page from scrolling.
  useEffect(() => {
    const c = canvasRef.current;
    if (!c) return;
    const onWheel = (e: WheelEvent) => {
      const p = pageRef.current;
      if (!p) return;
      e.preventDefault();
      const rect = c.getBoundingClientRect();
      const pt = clientToPage(e.clientX, e.clientY, rect, p, { clamp: true });
      if (!pt) return;
      const unit = e.deltaMode === 1 ? 16 : e.deltaMode === 2 ? rect.height : 1;
      // wheel deltas are already expressed in content pixels: forward them as-is
      send({ type: "scroll", x: pt.x, y: pt.y, dx: Math.round(e.deltaX * unit), dy: Math.round(e.deltaY * unit) });
    };
    c.addEventListener("wheel", onWheel, { passive: false });
    return () => c.removeEventListener("wheel", onWheel);
  }, [send]);

  const map = (clientX: number, clientY: number) => {
    const c = canvasRef.current;
    if (!c || !page) return null;
    return clientToPage(clientX, clientY, c.getBoundingClientRect(), page);
  };

  const onPointerDown = (e: RPointerEvent<HTMLCanvasElement>) => {
    if (!page) return;
    e.currentTarget.focus({ preventScroll: true });
    e.currentTarget.setPointerCapture?.(e.pointerId);
    gesture.current = {
      id: e.pointerId,
      type: e.pointerType,
      startX: e.clientX,
      startY: e.clientY,
      lastX: e.clientX,
      lastY: e.clientY,
      dragging: false,
      button: e.button,
    };
  };

  const onPointerMove = (e: RPointerEvent<HTMLCanvasElement>) => {
    const g = gesture.current;
    const c = canvasRef.current;
    if (!c || !page) return;
    if (!g || g.id !== e.pointerId) {
      if (e.pointerType === "mouse") {
        const now = performance.now();
        if (now - lastMove.current < MOUSEMOVE_MS) return;
        lastMove.current = now;
        const pt = map(e.clientX, e.clientY);
        if (pt) send({ type: "mousemove", ...pt });
      }
      return;
    }
    if (!g.dragging && Math.hypot(e.clientX - g.startX, e.clientY - g.startY) > TAP_SLOP) g.dragging = true;
    if (!g.dragging) return;
    const rect = c.getBoundingClientRect();
    const d = deltaToPage(g.lastX - e.clientX, g.lastY - e.clientY, rect, page);
    g.lastX = e.clientX;
    g.lastY = e.clientY;
    if (!d.dx && !d.dy) return;
    const at = clientToPage(g.startX, g.startY, rect, page, { clamp: true });
    if (at) send({ type: "scroll", x: at.x, y: at.y, dx: d.dx, dy: d.dy });
  };

  const onPointerUp = (e: RPointerEvent<HTMLCanvasElement>) => {
    const g = gesture.current;
    gesture.current = null;
    if (!g || g.id !== e.pointerId || g.dragging) return;
    const pt = map(e.clientX, e.clientY);
    if (!pt) return;
    if (g.type === "mouse") send({ type: "click", ...pt, button: g.button === 2 ? "right" : "left" });
    else send({ type: "tap", ...pt });
  };

  const onKeyDown = (e: React.KeyboardEvent<HTMLCanvasElement>) => {
    if (e.metaKey || e.ctrlKey || e.altKey) return;
    const key = toPlaywrightKey(e.key);
    if (key) {
      e.preventDefault();
      send({ type: "key", key });
    } else if (e.key.length === 1) {
      e.preventDefault();
      send({ type: "text", text: e.key });
    }
  };

  return (
    <div className={cn("relative min-h-0 flex-1 overflow-hidden bg-neutral-950", className)}>
      <canvas
        ref={canvasRef}
        tabIndex={0}
        role="application"
        aria-label={t("remote.label")}
        data-testid="remote-canvas"
        onPointerDown={onPointerDown}
        onPointerMove={onPointerMove}
        onPointerUp={onPointerUp}
        onPointerCancel={() => (gesture.current = null)}
        onContextMenu={(e) => e.preventDefault()}
        onKeyDown={onKeyDown}
        className="size-full touch-none object-contain outline-none select-none"
      />
      {!hasFrame && !closed && !reconnecting && !failed && <MediaOverlay spinner message={t("remote.loading")} />}
      {reconnecting && <MediaOverlay role="status" tone="dim" spinner message={t("remote.reconnecting")} />}
      {failed && (
        <MediaOverlay
          role="alert"
          tone="dim"
          icon={WifiOff}
          message={t("remote.lost")}
          action={onRetry ? { label: t("common.retry"), icon: RotateCw, onClick: onRetry } : undefined}
        />
      )}
      {closed && (
        <MediaOverlay
          role="alert"
          tone="dim"
          icon={MonitorX}
          message={t("remote.closed")}
          action={onReopen ? { label: t("remote.reopen"), icon: RotateCw, onClick: onReopen } : undefined}
        />
      )}
    </div>
  );
}
