"use client";

import { useQueryClient } from "@tanstack/react-query";
import { useCallback, useState } from "react";
import { toast } from "sonner";
import { api } from "@/lib/api";
import type { Channel, PlayerState, Settings, SourceKind } from "@/lib/api/types";
import { haptic } from "@/lib/haptics";
import { errorMessage, qk } from "@/lib/query";
import { selectActiveDevice, useAppStore } from "@/stores/app-store";
import { useUiStore } from "@/stores/ui-store";

export interface CastRequest {
  input: string;
  kind?: SourceKind;
  title?: string;
  enqueue?: boolean;
  /** Upstream headers the source needs (IPTV channel Referer/User-Agent). */
  headers?: Record<string, string> | null;
}

/** Cast request for an M3U channel, carrying the headers the playlist declared for it. */
export function channelRequest(c: Pick<Channel, "url" | "name" | "headers">, enqueue = false): CastRequest {
  const headers = c.headers && Object.keys(c.headers).length ? c.headers : undefined;
  return { input: c.url, title: c.name, ...(headers ? { headers } : {}), ...(enqueue ? { enqueue } : {}) };
}

/**
 * Returns the id of the device to cast to: the active one, else the default device from settings,
 * else asks the user via the device sheet.
 *
 * It never connects by itself: play / queue / browser cast auto-connect on the backend, and an explicit
 * `connect` first would LOAD the idle image (show_idle_on_connect) only to replace it with the media a
 * moment later — a visible flash on the TV and a slower start.
 */
export async function ensureDevice(settings: Settings | undefined): Promise<string | null> {
  const s = useAppStore.getState();
  const active = selectActiveDevice(s);
  if (active && s.appState?.players[active.id]?.connected) return active.id;
  const fallbackId = active?.id ?? settings?.default_device_id ?? null;
  const fallback = s.appState?.devices.find((d) => d.id === fallbackId && d.online);
  if (fallback) {
    // the backend makes it active on auto-connect; mirror that now so the UI follows immediately
    s.setActiveDevice(fallback.id);
    return fallback.id;
  }
  return useUiStore.getState().requestDevice();
}

function deviceName(id: string): string {
  return useAppStore.getState().appState?.devices.find((d) => d.id === id)?.name ?? "Chromecast";
}

/** Cast helpers shared by every page: picks a device if needed, toasts the outcome. */
export function useCast() {
  const qc = useQueryClient();
  const [busy, setBusy] = useState(false);

  const withDevice = useCallback(
    async (label: string, fn: (deviceId: string) => Promise<PlayerState>, enqueue?: boolean) => {
      const deviceId = await ensureDevice(qc.getQueryData<Settings>(qk.settings));
      if (!deviceId) return null;
      setBusy(true);
      haptic(12);
      const id = toast.loading(enqueue ? "Aggiunta alla coda…" : `Avvio su ${deviceName(deviceId)}…`, {
        description: label,
      });
      try {
        const p = await fn(deviceId);
        useAppStore.getState().applyPlayer(p);
        toast.success(enqueue ? "Aggiunto alla coda" : `In riproduzione su ${deviceName(deviceId)}`, {
          id,
          description: p.title ?? label,
        });
        qc.invalidateQueries({ queryKey: qk.history });
        return p;
      } catch (err) {
        toast.error(errorMessage(err, "Cast non riuscito"), { id, description: label });
        return null;
      } finally {
        setBusy(false);
      }
    },
    [qc],
  );

  const cast = useCallback(
    (req: CastRequest) =>
      withDevice(
        req.title ?? req.input,
        (deviceId) => {
          const body = { input: req.input, kind: req.kind, title: req.title, ...(req.headers ? { headers: req.headers } : {}) };
          return req.enqueue
            ? api.player.enqueue(deviceId, body)
            : api.player.play(deviceId, { ...body, enqueue: false });
        },
        req.enqueue,
      ),
    [withDevice],
  );

  const castCaptured = useCallback(
    (sessionId: string, streamId: string, opts: { title?: string; enqueue?: boolean } = {}) =>
      withDevice(
        opts.title ?? "Stream rilevato",
        (deviceId) =>
          api.browser.cast(sessionId, { stream_id: streamId, device_id: deviceId, enqueue: !!opts.enqueue }),
        opts.enqueue,
      ),
    [withDevice],
  );

  return { cast, castCaptured, busy };
}
