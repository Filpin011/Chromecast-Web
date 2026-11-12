"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Loader2 } from "lucide-react";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useCallback, useEffect, useRef, useState } from "react";
import { toast } from "sonner";
import { BrowserStart } from "@/components/browser/browser-start";
import { BrowserWorkspace } from "@/components/browser/browser-workspace";
import { api, ApiError } from "@/lib/api";
import type { BrowserSession } from "@/lib/api/types";
import { fitViewport, measureScreen, type ViewportMode } from "@/lib/browser-session";
import { errorMessage, qk } from "@/lib/query";
import { readStorage, writeStorage } from "@/lib/storage";

const SESSION_KEY = "cw.browser.session";
const MODE_KEY = "cw.browser.mode";
const homeKey = (id: string) => `cw.browser.home.${id}`;

function BrowserPageInner() {
  const params = useSearchParams();
  const router = useRouter();
  const qc = useQueryClient();
  const [current, setCurrentState] = useState<BrowserSession | null>(null);
  const [mode, setModeState] = useState<ViewportMode>(() => (readStorage(MODE_KEY) === "desktop" ? "desktop" : "mobile"));
  const [opening, setOpening] = useState(false);
  /** Focus the address field when the start screen is reached through "+" (new session). */
  const [focusUrl, setFocusUrl] = useState(false);
  const sessions = useQuery({ queryKey: qk.browserSessions, queryFn: () => api.browser.list(), refetchInterval: current ? false : 10_000 });

  const setCurrent = useCallback((s: BrowserSession | null) => {
    setCurrentState(s);
    if (s) setFocusUrl(false);
    writeStorage(SESSION_KEY, s?.id ?? null);
  }, []);

  const setMode = (m: ViewportMode) => {
    setModeState(m);
    writeStorage(MODE_KEY, m);
  };

  const open = useCallback(
    async (url: string, m: ViewportMode = mode, replaceId?: string) => {
      setOpening(true);
      try {
        const home = replaceId ? readStorage(homeKey(replaceId)) : null;
        if (replaceId) {
          await api.browser.close(replaceId).catch(() => {});
          writeStorage(homeKey(replaceId), null);
        }
        // sized to the space the phone actually has, so the page is drawn 1:1 (no letterboxing)
        const s = await api.browser.create(url, fitViewport(m, measureScreen()));
        writeStorage(homeKey(s.id), home ?? url);
        setCurrent(s);
      } catch (e) {
        toast.error(errorMessage(e, "Impossibile aprire la pagina"), {
          description: "Al massimo 2 sessioni contemporanee: chiudine una dalla schermata Browser.",
        });
      } finally {
        setOpening(false);
        qc.invalidateQueries({ queryKey: qk.browserSessions });
      }
    },
    [mode, qc, setCurrent],
  );

  // Deep link (?url=…) opens a session; otherwise resume the last one.
  const booted = useRef(false);
  useEffect(() => {
    if (booted.current) return;
    booted.current = true;
    const url = params.get("url");
    if (url) {
      router.replace("/browser/");
      // deferred: not a synchronous state update inside the effect (no cleanup: runs once even in StrictMode)
      setTimeout(() => void open(url), 0);
      return;
    }
    const saved = readStorage(SESSION_KEY);
    if (saved) {
      api.browser
        .get(saved)
        .then((s) => setCurrent(s))
        .catch(() => writeStorage(SESSION_KEY, null));
    }
  }, [params, router, open, setCurrent]);

  // Quick close: leave the session screen immediately (no confirmation), tear down in the background.
  const close = async (s: BrowserSession) => {
    if (current?.id === s.id) setCurrent(null);
    writeStorage(homeKey(s.id), null);
    qc.setQueryData<BrowserSession[]>(qk.browserSessions, (old) => old?.filter((x) => x.id !== s.id));
    try {
      await api.browser.close(s.id);
    } catch (e) {
      if (!ApiError.isCode(e, "session_not_found")) toast.error(errorMessage(e));
    }
    qc.invalidateQueries({ queryKey: qk.browserSessions });
  };

  const list = sessions.data ?? [];
  if (current) {
    return (
      <BrowserWorkspace
        key={current.id}
        session={current}
        sessions={list}
        homeUrl={readStorage(homeKey(current.id)) ?? current.url}
        onNewSession={() => {
          setFocusUrl(true);
          setCurrent(null);
        }}
        onSwitchSession={setCurrent}
        onCloseSession={(s) => void close(s)}
        onClose={() => close(current)}
        onReopen={(m, url) => {
          setMode(m);
          void open(url, m, current.id);
        }}
      />
    );
  }
  return (
    <>
      <BrowserStart
        sessions={list}
        mode={mode}
        onModeChange={setMode}
        onOpen={(url) => open(url)}
        onResume={setCurrent}
        onCloseSession={close}
        busy={opening}
        autoFocus={focusUrl}
      />
      {opening && (
        <div className="fixed inset-0 z-50 grid place-items-center bg-background/70 backdrop-blur-sm">
          <div className="flex flex-col items-center gap-3 text-sm text-muted-foreground">
            <Loader2 className="size-8 animate-spin text-primary" />
            Apertura pagina sul server…
          </div>
        </div>
      )}
    </>
  );
}

export default function BrowserPage() {
  return (
    <Suspense fallback={null}>
      <BrowserPageInner />
    </Suspense>
  );
}
