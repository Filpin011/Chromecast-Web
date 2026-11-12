"use client";

import { useEffect } from "react";
import { toast } from "sonner";
import { api } from "@/lib/api";
import type { ServerMessage } from "@/lib/api/types";
import { currentTranslator } from "@/i18n";
import { translateErrorCode } from "@/lib/query";
import { StateSocket } from "@/lib/ws";
import { useAppStore } from "@/stores/app-store";

type ToastMsg = Extract<ServerMessage, { type: "toast" }>;

/**
 * Text of a server toast in the current language: known codes are translated (interpolating
 * `params`), anything else falls back to the server's English `message`.
 */
export function toastText(msg: ToastMsg): string {
  const tr = currentTranslator();
  const params = msg.params ?? {};
  if (msg.code === "queue_skipped") {
    const why =
      translateErrorCode(String(params.error_code ?? "") || undefined, String(params.error_reason ?? "") || undefined, params, tr) ||
      String(params.detail ?? "");
    return tr("toast.queue_skipped", { ...params, reason: why });
  }
  return (msg.code && tr.maybe(`toast.${msg.code}`, params)) || msg.message;
}

/** Dispatch one `/ws` message into the store / toaster. Exported for tests. */
export function handleServerMessage(msg: ServerMessage): void {
  switch (msg.type) {
    case "state":
      useAppStore.getState().applySnapshot(msg.data);
      break;
    case "toast":
      if (msg.level === "error") toast.error(toastText(msg));
      else if (msg.level === "success") toast.success(toastText(msg));
      else toast(toastText(msg));
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
