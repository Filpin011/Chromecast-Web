"use client";

import { useEffect } from "react";
import { toast } from "sonner";
import { api } from "@/lib/api";
import type { ServerMessage } from "@/lib/api/types";
import { StateSocket } from "@/lib/ws";
import { useAppStore } from "@/stores/app-store";

/** Dispatch one `/ws` message into the store / toaster. Exported for tests. */
export function handleServerMessage(msg: ServerMessage): void {
  switch (msg.type) {
    case "state":
      useAppStore.getState().applySnapshot(msg.data);
      break;
    case "toast":
      if (msg.level === "error") toast.error(msg.message);
      else if (msg.level === "success") toast.success(msg.message);
      else toast(msg.message);
      break;
    default:
      break;
  }
}

/** Keeps the zustand store in sync with the server through `/ws` (mounted once in the providers). */
export function StateSocketBridge() {
  useEffect(() => {
    const socket = new StateSocket();
    const offStatus = socket.onStatus((s) => useAppStore.getState().setConnection(s));
    const offMsg = socket.onMessage(handleServerMessage);
    socket.connect();

    // REST fallback so the UI has data even if the socket is slow to open.
    api.system
      .state()
      .then((s) => {
        if (!useAppStore.getState().appState) useAppStore.getState().applySnapshot(s);
      })
      .catch(() => {});

    const onVisible = () => {
      if (document.visibilityState === "visible") socket.reconnectNow();
    };
    const onOnline = () => socket.reconnectNow();
    document.addEventListener("visibilitychange", onVisible);
    window.addEventListener("online", onOnline);
    return () => {
      document.removeEventListener("visibilitychange", onVisible);
      window.removeEventListener("online", onOnline);
      offStatus();
      offMsg();
      socket.close();
    };
  }, []);
  return null;
}
