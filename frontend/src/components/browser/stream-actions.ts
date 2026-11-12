"use client";

import { useQueryClient } from "@tanstack/react-query";
import { useCallback } from "react";
import { toast } from "sonner";
import { useCast } from "@/hooks/use-cast";
import { api } from "@/lib/api";
import type { CapturedStream } from "@/lib/api/types";
import { errorMessage, qk } from "@/lib/query";

export interface StreamActions {
  cast: (s: CapturedStream) => void;
  queue: (s: CapturedStream) => void;
  favorite: (s: CapturedStream) => void;
  busy: boolean;
}

/** Cast / queue / bookmark a stream captured by a remote browser session. */
export function useStreamActions(sessionId: string | null, pageTitle?: string | null): StreamActions {
  const { castCaptured, busy } = useCast();
  const qc = useQueryClient();
  const titleOf = useCallback((s: CapturedStream) => s.title || pageTitle || "Stream rilevato", [pageTitle]);

  const cast = useCallback(
    (s: CapturedStream) => {
      if (sessionId) void castCaptured(sessionId, s.id, { title: titleOf(s) });
    },
    [sessionId, castCaptured, titleOf],
  );
  const queue = useCallback(
    (s: CapturedStream) => {
      if (sessionId) void castCaptured(sessionId, s.id, { title: titleOf(s), enqueue: true });
    },
    [sessionId, castCaptured, titleOf],
  );
  const favorite = useCallback(
    async (s: CapturedStream) => {
      if (!sessionId) return;
      try {
        await api.browser.favorite(sessionId, s.id);
        qc.invalidateQueries({ queryKey: qk.favorites });
        toast.success("Aggiunto ai preferiti", { description: titleOf(s) });
      } catch (e) {
        toast.error(errorMessage(e));
      }
    },
    [sessionId, qc, titleOf],
  );
  return { cast, queue, favorite, busy };
}
