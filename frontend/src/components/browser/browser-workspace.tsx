"use client";

import {
  ArrowLeft,
  ArrowRight,
  Home,
  Keyboard,
  Menu,
  Monitor,
  MoreHorizontal,
  Plus,
  Maximize2,
  Radar,
  Smartphone,
  Square,
  X,
} from "lucide-react";
import { AnimatePresence } from "motion/react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { toast } from "sonner";
import { DeviceButton } from "@/components/devices/device-button";
import { Button } from "@/components/ui/button";
import { Drawer, DrawerContent, DrawerTitle } from "@/components/ui/drawer";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { useBrowserSession, type FrameSink } from "@/hooks/use-browser-session";
import { api } from "@/lib/api";
import type { BrowserSession, CapturedStream, PopupDecision } from "@/lib/api/types";
import {
  fitViewport,
  measureScreen,
  nextPopup,
  pageSize,
  PHONE_LAYOUT_MAX,
  viewportMismatch,
  viewportMode,
  type ViewportMode,
} from "@/lib/browser-session";
import { rankCaptured } from "@/lib/captured";
import { haptic } from "@/lib/haptics";
import { cn } from "@/lib/utils";
import { errorMessage } from "@/lib/query";
import { useUiStore } from "@/stores/ui-store";
import { AdblockButton } from "./adblock-button";
import { AppMenuSheet, SessionsSheet } from "./browser-sheets";
import { CapturedList } from "./captured-list";
import { KeyboardBar } from "./keyboard-bar";
import { PopupPrompt } from "./popup-prompt";
import { PreviewDialog } from "./preview-dialog";
import { RemoteView } from "./remote-view";
import { useStreamActions } from "./stream-actions";
import { StreamPanel } from "./stream-panel";
import { UrlField } from "./url-field";

type Sink = FrameSink & { snapshot: () => string | null };

export interface BrowserWorkspaceProps {
  session: BrowserSession;
  /** Every open session (the "tabs"), for the sessions sheet. */
  sessions: BrowserSession[];
  /** Page the Home button loads in the remote browser (the URL this session was opened with). */
  homeUrl: string;
  /** Back to the start screen with the address field focused. */
  onNewSession: () => void;
  onSwitchSession: (s: BrowserSession) => void;
  /** Close any session from the sessions sheet. */
  onCloseSession: (s: BrowserSession) => void;
  /** Quick close of this session (no confirmation). */
  onClose: () => void;
  /** Replace this session with a new one on `url` (viewport switch, fit to screen, reopen after close). */
  onReopen: (mode: ViewportMode, url: string) => void;
}

/** Space the phone has for the remote page, re-measured on resize / rotation. */
function useFittedViewport() {
  const [fitted, setFitted] = useState<{ width: number; height: number } | null>(null);
  useEffect(() => {
    let t: ReturnType<typeof setTimeout> | undefined;
    const update = () => {
      clearTimeout(t);
      t = setTimeout(() => {
        // the on-screen keyboard shrinks the window while typing: that is not a new screen size
        const el = document.activeElement;
        if (el instanceof HTMLInputElement || el instanceof HTMLTextAreaElement) return;
        const screen = measureScreen();
        setFitted(screen && screen.width <= PHONE_LAYOUT_MAX ? fitViewport("mobile", screen) : null);
      }, 250);
    };
    update();
    window.addEventListener("resize", update);
    window.addEventListener("orientationchange", update);
    return () => {
      clearTimeout(t);
      window.removeEventListener("resize", update);
      window.removeEventListener("orientationchange", update);
    };
  }, []);
  return fitted;
}

export function BrowserWorkspace({
  session: initial,
  sessions,
  homeUrl,
  onNewSession,
  onSwitchSession,
  onCloseSession,
  onClose,
  onReopen,
}: BrowserWorkspaceProps) {
  const { state, send, setSink, dispatch, retry } = useBrowserSession(initial);
  const [menuOpen, setMenuOpen] = useState(false);
  const [sessionsOpen, setSessionsOpen] = useState(false);
  const [adblockBusy, setAdblockBusy] = useState(false);
  const session = state.session ?? initial;
  const sinkRef = useRef<Sink | null>(null);
  const [keyboard, setKeyboard] = useState(false);
  const [listOpen, setListOpen] = useState(false);
  const [preview, setPreview] = useState<CapturedStream | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [dismissedTop, setDismissedTop] = useState<string | null>(null);
  const [snapshots, setSnapshots] = useState<Record<string, string>>({});
  const actions = useStreamActions(session.id, session.title);

  const ranked = useMemo(() => rankCaptured(state.captured), [state.captured]);
  const top = ranked[0] ?? null;
  const panelOpen = !!top && top.id !== dismissedTop;
  // the keyboard bar overlays the bottom of the page; the big stream panel steps aside meanwhile
  // (the "N video" pill stays reachable above the bar)
  const panelVisible = panelOpen && !keyboard;
  const mode = viewportMode(session.viewport);
  const fitted = useFittedViewport();
  const canFit = mode === "mobile" && !!fitted && !!session.viewport && viewportMismatch(session.viewport, fitted);
  const tabs = useMemo(
    () => (sessions.some((s) => s.id === session.id) ? sessions : [session, ...sessions]),
    [sessions, session],
  );

  // Full height on phones: the shell hides its tab bar (and mini player) while this is mounted.
  const setImmersive = useUiStore((s) => s.setImmersive);
  useEffect(() => {
    setImmersive(true);
    return () => setImmersive(false);
  }, [setImmersive]);

  const onSink = useCallback(
    (sink: Sink | null) => {
      sinkRef.current = sink;
      setSink(sink);
    },
    [setSink],
  );

  // Snapshot the page as a thumbnail for streams the backend didn't give one — only once a frame is
  // on screen (captures can arrive on `init` before any frame); a blank snapshot would stick for good.
  const snapped = useRef(new Set<string>());
  const hasFrame = !!state.frameSize;
  useEffect(() => {
    if (!hasFrame) return;
    const missing = state.captured.filter((c) => !c.thumbnail && !snapped.current.has(c.id));
    if (!missing.length) return;
    const t = setTimeout(() => {
      const shot = sinkRef.current?.snapshot();
      if (!shot) return;
      missing.forEach((c) => snapped.current.add(c.id));
      setSnapshots((prev) => ({ ...prev, ...Object.fromEntries(missing.map((c) => [c.id, shot])) }));
    }, 600);
    return () => clearTimeout(t);
  }, [state.captured, hasFrame]);

  // Haptic + toast when the first stream shows up.
  const hadStreams = useRef(false);
  useEffect(() => {
    if (top && !hadStreams.current) {
      hadStreams.current = true;
      haptic([10, 40, 10]);
    }
  }, [top]);

  const navigate = async (req: { url: string } | { action: "back" | "forward" | "reload" }) => {
    haptic(6);
    try {
      await api.browser.navigate(session.id, req);
    } catch (e) {
      toast.error(errorMessage(e, "Navigazione non riuscita"));
    }
  };

  const page = pageSize({ session, frameSize: state.frameSize });
  const popup = nextPopup(session);
  const morePopups = Math.max(0, (session.pending_popups?.length ?? 0) - 1);

  const toggleAdblock = async (enabled: boolean) => {
    haptic(8);
    setAdblockBusy(true);
    try {
      dispatch({ type: "session", data: await api.browser.setAdblock(session.id, enabled) });
      toast.success(enabled ? "Blocco pubblicità attivato su questo sito" : "Blocco pubblicità disattivato su questo sito");
    } catch (e) {
      toast.error(errorMessage(e, "Impossibile cambiare il blocco pubblicità"));
    } finally {
      setAdblockBusy(false);
    }
  };

  const decidePopup = (decision: PopupDecision) => {
    if (!popup) return;
    haptic(6);
    dispatch({ type: "popup_resolved", id: popup.id });
    // over the live socket when connected, REST otherwise
    if (!send({ type: "popup_decision", id: popup.id, decision })) {
      api.browser.popupDecision(session.id, popup.id, decision).catch((e) => toast.error(errorMessage(e)));
    }
    if (decision === "block_always") toast.success("Popup bloccati per sempre su questo sito");
  };

  const stopMedia = () => {
    haptic(6);
    send({ type: "stop_media" });
  };

  return (
    <div className="flex h-viewport min-h-0 flex-col">
      {/* Top bar: every control is a 44px target; reload lives inside the URL pill */}
      <div className="flex items-center gap-1 border-b bg-background/95 px-1 pt-safe backdrop-blur">
        <div className="flex h-14 w-full items-center gap-0.5">
          <Button variant="ghost" size="icon" className="shrink-0" aria-label="Menu" onClick={() => setMenuOpen(true)}>
            <Menu className="size-5" />
          </Button>
          <UrlField
            key={session.url}
            url={session.url}
            onNavigate={(url) => navigate({ url })}
            onReload={() => navigate({ action: "reload" })}
          />
          <AdblockButton
            url={session.url}
            enabled={session.adblock_enabled ?? false}
            blocked={session.blocked_count ?? 0}
            busy={adblockBusy}
            onToggle={toggleAdblock}
            onStopMedia={stopMedia}
          />
          <DeviceButton className="shrink-0" />
          <Button
            variant="ghost"
            size="icon"
            className="shrink-0 bg-destructive/10 text-destructive hover:bg-destructive/20"
            aria-label="Chiudi subito la sessione"
            onClick={() => {
              haptic(12);
              onClose();
            }}
          >
            <X className="size-5" />
          </Button>
        </div>
      </div>

      <div className="relative flex min-h-0 flex-1">
        <div className="relative flex min-h-0 min-w-0 flex-1 flex-col">
          <AnimatePresence>
            {popup && <PopupPrompt key={popup.id} popup={popup} more={morePopups} onDecide={decidePopup} />}
          </AnimatePresence>
          <RemoteView
            page={page}
            hasFrame={!!state.frameSize}
            closed={state.closed}
            status={state.status}
            send={send}
            onSink={onSink}
            onRetry={retry}
            onReopen={() => onReopen(mode, session.url)}
          />
          {canFit && !state.closed && (
            <button
              type="button"
              onClick={() => onReopen("mobile", session.url)}
              className="absolute top-2 left-1/2 z-10 flex h-11 -translate-x-1/2 items-center gap-2 rounded-full bg-background/90 px-4 text-sm font-medium shadow-lg backdrop-blur"
            >
              <Maximize2 className="size-4" /> Adatta allo schermo
            </button>
          )}
          <div className="md:hidden">
            <AnimatePresence>
              {panelVisible && (
                <StreamPanel
                  streams={ranked}
                  selectedId={selectedId}
                  onSelect={setSelectedId}
                  snapshots={snapshots}
                  pageTitle={session.title}
                  onDismiss={() => setDismissedTop(top?.id ?? null)}
                  onCast={actions.cast}
                  onQueue={actions.queue}
                  onPlay={setPreview}
                  onBookmark={actions.favorite}
                  busy={actions.busy}
                />
              )}
            </AnimatePresence>
          </div>
          {!panelVisible && ranked.length > 0 && (
            <button
              type="button"
              onClick={() => {
                setKeyboard(false);
                setDismissedTop(null);
              }}
              className={cn(
                "absolute right-3 z-10 flex h-11 items-center gap-2 rounded-full bg-primary px-4 text-sm font-semibold text-primary-foreground shadow-lg md:hidden",
                keyboard ? "bottom-17" : "bottom-3",
              )}
            >
              <Radar className="size-4" /> {ranked.length} video
            </button>
          )}
          {/* Overlay, not a flex row: the session viewport is fitted 1:1 to this area, so taking
              height from it would letterbox and shrink the page right when the user aims at a field. */}
          {keyboard && <KeyboardBar send={send} autoFocus className="absolute inset-x-0 bottom-0 z-30 shadow-lg" />}
        </div>
        <aside className="hidden w-80 shrink-0 flex-col border-l bg-background md:flex lg:w-96">
          <div className="flex items-center justify-between border-b px-4 py-3">
            <h2 className="text-sm font-semibold">Stream rilevati</h2>
            <span className="rounded-full bg-muted px-2 py-0.5 text-xs font-medium tabular-nums">{ranked.length}</span>
          </div>
          <div className="min-h-0 flex-1 overflow-y-auto p-3">
            <CapturedList
              streams={ranked}
              snapshots={snapshots}
              onPreview={setPreview}
              onCast={actions.cast}
              onQueue={actions.queue}
              onBookmark={actions.favorite}
              busy={actions.busy}
            />
          </div>
        </aside>
      </div>

      {/* Bottom toolbar */}
      <nav aria-label="Navigazione browser" className="shrink-0 border-t bg-background/95 pb-safe backdrop-blur">
        <div className="grid h-13 grid-cols-7">
        <Button variant="ghost" className="h-full rounded-none" aria-label="Indietro" onClick={() => navigate({ action: "back" })}>
          <ArrowLeft className="size-5" />
        </Button>
        <Button variant="ghost" className="h-full rounded-none" aria-label="Avanti" onClick={() => navigate({ action: "forward" })}>
          <ArrowRight className="size-5" />
        </Button>
        <Button variant="ghost" className="h-full rounded-none" aria-label="Pagina iniziale" onClick={() => navigate({ url: homeUrl })}>
          <Home className="size-5" />
        </Button>
        <Button
          variant="ghost"
          className={cn("h-full rounded-none", keyboard && "text-primary")}
          aria-label={keyboard ? "Nascondi tastiera" : "Tastiera"}
          aria-pressed={keyboard}
          onClick={() => setKeyboard((k) => !k)}
        >
          <Keyboard className="size-5" />
        </Button>
        <Button variant="ghost" className="h-full rounded-none" aria-label={`${tabs.length} sessioni aperte`} onClick={() => setSessionsOpen(true)}>
          <span className="grid size-6 place-items-center rounded-md border-2 border-current text-[0.7rem] font-bold">{tabs.length}</span>
        </Button>
        <Button variant="ghost" className="h-full rounded-none" aria-label="Nuova sessione" onClick={onNewSession}>
          <Plus className="size-5" />
        </Button>
        <DropdownMenu>
          <DropdownMenuTrigger render={<Button variant="ghost" className="h-full rounded-none" aria-label="Altro" />}>
            <MoreHorizontal className="size-5" />
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end" side="top" className="w-60">
            <DropdownMenuItem onClick={stopMedia}>
              <Square className="size-4" /> Ferma audio/video
            </DropdownMenuItem>
            <DropdownMenuItem onClick={() => setListOpen(true)} className="md:hidden">
              <Radar className="size-4" /> Stream rilevati ({ranked.length})
            </DropdownMenuItem>
            <DropdownMenuItem onClick={() => onReopen(mode === "mobile" ? "desktop" : "mobile", session.url)}>
              {mode === "mobile" ? <Monitor className="size-4" /> : <Smartphone className="size-4" />}
              {mode === "mobile" ? "Versione desktop" : "Versione mobile"}
            </DropdownMenuItem>
            <DropdownMenuSeparator />
            <DropdownMenuItem variant="destructive" onClick={onClose}>
              <X className="size-4" /> Chiudi sessione
            </DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>
        </div>
      </nav>

      <Drawer open={listOpen} onOpenChange={setListOpen} showSwipeHandle>
        <DrawerContent>
          <DrawerTitle className="px-4 pt-3 pb-2">Stream rilevati</DrawerTitle>
          <div className="overflow-y-auto px-4 pb-[max(env(safe-area-inset-bottom),1rem)]">
            <CapturedList
              streams={ranked}
              snapshots={snapshots}
              onPreview={(s) => {
                setListOpen(false);
                setPreview(s);
              }}
              onCast={actions.cast}
              onQueue={actions.queue}
              onBookmark={actions.favorite}
              busy={actions.busy}
            />
          </div>
        </DrawerContent>
      </Drawer>

      <AppMenuSheet open={menuOpen} onOpenChange={setMenuOpen} />
      <SessionsSheet
        open={sessionsOpen}
        onOpenChange={setSessionsOpen}
        sessions={tabs}
        currentId={session.id}
        onSwitch={onSwitchSession}
        onClose={(s) => {
          if (s.id === session.id) setSessionsOpen(false);
          onCloseSession(s);
        }}
        onNew={onNewSession}
      />

      <PreviewDialog stream={preview} title={preview?.title ?? session.title} onOpenChange={(o) => !o && setPreview(null)} />
    </div>
  );
}
