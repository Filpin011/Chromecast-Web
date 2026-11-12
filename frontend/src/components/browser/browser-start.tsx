"use client";

import { Compass, Monitor, Smartphone, X } from "lucide-react";
import { useState, type FormEvent } from "react";
import { Button } from "@/components/ui/button";
import type { BrowserSession } from "@/lib/api/types";
import type { ViewportMode } from "@/lib/browser-session";
import { hostOf } from "@/lib/format";
import { normalizeUrl } from "@/lib/url";
import { cn } from "@/lib/utils";

export function BrowserStart({
  sessions,
  mode,
  onModeChange,
  onOpen,
  onResume,
  onCloseSession,
  busy,
  autoFocus,
}: {
  sessions: BrowserSession[];
  mode: ViewportMode;
  onModeChange: (m: ViewportMode) => void;
  onOpen: (url: string) => void;
  onResume: (s: BrowserSession) => void;
  onCloseSession: (s: BrowserSession) => void;
  busy?: boolean;
  /** Focus the address field on mount (reached through "New session"). */
  autoFocus?: boolean;
}) {
  const [value, setValue] = useState("");
  const submit = (e: FormEvent) => {
    e.preventDefault();
    const u = normalizeUrl(value);
    if (u) onOpen(u);
  };
  return (
    <div className="mx-auto flex w-full max-w-xl flex-col gap-6 px-4 pt-[calc(env(safe-area-inset-top)+2rem)] pb-chrome">
      <div className="space-y-2 text-center">
        <div className="mx-auto grid size-16 place-items-center rounded-3xl bg-gradient-to-br from-primary to-indigo-700 text-white shadow-xl shadow-primary/30">
          <Compass className="size-8" />
        </div>
        <h1 className="text-2xl font-bold tracking-tight">Browser</h1>
        <p className="text-sm text-muted-foreground">
          Apri una pagina sul server, avvia il video e trasmettilo: gli stream vengono rilevati automaticamente.
        </p>
      </div>
      <form onSubmit={submit} className="space-y-3">
        <input
          aria-label="Indirizzo da aprire"
          autoFocus={autoFocus}
          value={value}
          onChange={(e) => setValue(e.target.value)}
          placeholder="Cerca o inserisci un indirizzo"
          inputMode="url"
          enterKeyHint="go"
          autoCapitalize="off"
          autoCorrect="off"
          spellCheck={false}
          className="h-13 w-full rounded-2xl border bg-card px-4 text-base shadow-sm outline-none focus:border-primary/60 focus:ring-4 focus:ring-primary/15"
        />
        <div className="flex gap-2">
          <div role="radiogroup" aria-label="Modalità" className="grid flex-1 grid-cols-2 gap-1 rounded-xl bg-muted p-1">
            {(
              [
                ["mobile", Smartphone, "Mobile"],
                ["desktop", Monitor, "Desktop"],
              ] as const
            ).map(([m, Icon, label]) => (
              <button
                key={m}
                type="button"
                role="radio"
                aria-checked={mode === m}
                onClick={() => onModeChange(m)}
                className={cn(
                  "flex h-9 items-center justify-center gap-1.5 rounded-lg text-sm font-medium",
                  mode === m ? "bg-background shadow-sm" : "text-muted-foreground",
                )}
              >
                <Icon className="size-4" /> {label}
              </button>
            ))}
          </div>
          <Button type="submit" size="lg" disabled={!value.trim() || busy} className="rounded-xl px-6">
            Apri
          </Button>
        </div>
      </form>
      {sessions.length > 0 && (
        <section className="space-y-2">
          <h2 className="px-1 text-sm font-semibold text-muted-foreground">Sessioni aperte</h2>
          <ul className="space-y-2">
            {sessions.map((s) => (
              <li key={s.id} className="flex items-center gap-1 rounded-2xl border bg-card">
                <button type="button" onClick={() => onResume(s)} className="flex min-h-16 min-w-0 flex-1 items-center gap-3 px-4 text-left">
                  <Compass className="size-5 shrink-0 text-primary" />
                  <span className="min-w-0">
                    <span className="block truncate text-sm font-medium">{s.title || hostOf(s.url)}</span>
                    <span className="block truncate text-xs text-muted-foreground">
                      {hostOf(s.url)} · {s.captured.length} stream
                    </span>
                  </span>
                </button>
                <Button variant="ghost" size="icon" aria-label={`Chiudi ${hostOf(s.url)}`} onClick={() => onCloseSession(s)} className="mr-1">
                  <X className="size-4" />
                </Button>
              </li>
            ))}
          </ul>
        </section>
      )}
    </div>
  );
}
