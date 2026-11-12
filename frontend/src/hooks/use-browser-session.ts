"use client";

import { useCallback, useEffect, useReducer, useRef } from "react";
import type { BrowserClientMsg, BrowserSession } from "@/lib/api/types";
import { browserViewReducer, initialBrowserView } from "@/lib/browser-session";
import { BrowserSocket } from "@/lib/ws";

export type FrameSink = (base64Jpeg: string, width: number, height: number) => void;

/** Draws base64 JPEG frames onto a canvas, dropping frames while a decode is in flight. */
export function createCanvasSink(canvas: HTMLCanvasElement): FrameSink & { snapshot: () => string | null } {
  let busy = false;
  // A fresh canvas is 300×150 and transparent: never snapshot it before a frame was actually drawn.
  let drawn = false;
  let pending: { data: string; w: number; h: number } | null = null;
  const draw = async (data: string, w: number, h: number) => {
    busy = true;
    try {
      const bin = atob(data);
      const bytes = new Uint8Array(bin.length);
      for (let i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i);
      const blob = new Blob([bytes], { type: "image/jpeg" });
      const bmp = await createImageBitmap(blob);
      if (canvas.width !== bmp.width || canvas.height !== bmp.height) {
        canvas.width = bmp.width || w;
        canvas.height = bmp.height || h;
      }
      const ctx = canvas.getContext("2d");
      if (ctx) {
        ctx.drawImage(bmp, 0, 0);
        drawn = true;
      }
      bmp.close?.();
    } catch {
      /* corrupt frame: skip */
    } finally {
      busy = false;
      if (pending) {
        const p = pending;
        pending = null;
        void draw(p.data, p.w, p.h);
      }
    }
  };
  const sink = ((data: string, w: number, h: number) => {
    if (busy) {
      pending = { data, w, h };
      return;
    }
    void draw(data, w, h);
  }) as FrameSink & { snapshot: () => string | null };
  sink.snapshot = () => {
    try {
      if (!drawn || !canvas.width) return null;
      const scale = Math.min(1, 320 / canvas.width);
      const c = document.createElement("canvas");
      c.width = Math.round(canvas.width * scale);
      c.height = Math.round(canvas.height * scale);
      c.getContext("2d")?.drawImage(canvas, 0, 0, c.width, c.height);
      return c.toDataURL("image/jpeg", 0.7);
    } catch {
      return null;
    }
  };
  return sink;
}

/** Live connection to `/ws/browser/{id}`: session/captured state + a frame sink + input sender. */
export function useBrowserSession(initial: BrowserSession | null) {
  const [state, dispatch] = useReducer(browserViewReducer, initialBrowserView);
  const socketRef = useRef<BrowserSocket | null>(null);
  const sinkRef = useRef<FrameSink | null>(null);
  const sessionId = initial?.id ?? null;
  const initialRef = useRef(initial);
  useEffect(() => {
    initialRef.current = initial;
  });

  useEffect(() => {
    const init = initialRef.current;
    if (!sessionId || !init) return;
    dispatch({ type: "init", session: init });
    const socket = new BrowserSocket(sessionId);
    socketRef.current = socket;
    const offStatus = socket.onStatus((status) =>
      dispatch({ type: "status", status: status === "closed" && socket.gaveUp ? "failed" : status }),
    );
    const offMsg = socket.onMessage((msg) => {
      if (msg.type === "frame") {
        sinkRef.current?.(msg.data, msg.width, msg.height);
      }
      dispatch(msg);
      if (msg.type === "closed") socket.close();
    });
    socket.connect();
    return () => {
      offStatus();
      offMsg();
      socket.close();
      socketRef.current = null;
    };
  }, [sessionId]);

  const send = useCallback((msg: BrowserClientMsg) => socketRef.current?.send(msg) ?? false, []);
  /** Reconnect the viewer socket after it gave up. */
  const retry = useCallback(() => socketRef.current?.retry(), []);
  const setSink = useCallback((sink: FrameSink | null) => {
    sinkRef.current = sink;
  }, []);

  return { state, send, setSink, dispatch, retry };
}
