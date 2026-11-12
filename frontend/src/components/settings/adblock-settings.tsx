"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Loader2, RefreshCw, X } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Switch } from "@/components/ui/switch";
import { api } from "@/lib/api";
import type { PopupPolicy, Settings } from "@/lib/api/types";
import { formatRelative } from "@/lib/format";
import { errorMessage } from "@/lib/query";
import { cn } from "@/lib/utils";

const POLICIES: { value: PopupPolicy; label: string; hint: string }[] = [
  { value: "ask", label: "Chiedi", hint: "Mostra «La pagina vuole aprire…» e decidi tu." },
  { value: "block", label: "Blocca", hint: "Chiude ogni popup e nuova scheda senza chiedere." },
  { value: "allow", label: "Consenti", hint: "Apre i popup non pubblicitari nella sessione." },
];

const FILTERS_KEY = ["filters"] as const;

function HostList({
  label,
  empty,
  hosts,
  onRemove,
}: {
  label: string;
  empty: string;
  hosts: string[];
  onRemove: (host: string) => void;
}) {
  return (
    <div className="px-4 py-3">
      <p className="text-sm font-medium">{label}</p>
      {hosts.length === 0 ? (
        <p className="text-xs text-muted-foreground">{empty}</p>
      ) : (
        <ul className="mt-2 flex flex-wrap gap-1.5">
          {hosts.map((h) => (
            <li key={h} className="flex h-8 items-center gap-1 rounded-full bg-muted pr-1 pl-3 text-xs">
              <span className="max-w-48 truncate">{h}</span>
              <button
                type="button"
                aria-label={`Rimuovi ${h}`}
                onClick={() => onRemove(h)}
                className="grid size-6 place-items-center rounded-full text-muted-foreground hover:bg-background hover:text-foreground"
              >
                <X className="size-3.5" />
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

/** "Browser e pubblicità": global ad-block switch, popup policy, per-site lists, filter lists. */
export function AdblockSettings({ settings: s, onChange }: { settings: Settings | undefined; onChange: (patch: Partial<Settings>) => void }) {
  const qc = useQueryClient();
  const filters = useQuery({ queryKey: FILTERS_KEY, queryFn: () => api.filters.list(), staleTime: 60_000 });
  const refresh = useMutation({
    mutationFn: () => api.filters.refresh(),
    onSuccess: (data) => {
      qc.setQueryData(FILTERS_KEY, data);
      toast.success("Liste filtri aggiornate");
    },
    onError: (e) => toast.error(errorMessage(e, "Aggiornamento liste non riuscito")),
  });
  const lists = filters.data?.lists ?? [];
  const totalRules = lists.reduce((n, l) => n + l.rules, 0);
  const policy = s?.popup_policy ?? "ask";

  return (
    <>
      <div className="flex min-h-14 items-center gap-3 px-4 py-3">
        <div className="min-w-0 flex-1">
          <label htmlFor="adblock-enabled" className="block text-sm font-medium">
            Blocco pubblicità
          </label>
          <p className="text-xs text-muted-foreground">Filtri di uBlock Origin nel browser remoto (rete + elementi nascosti).</p>
        </div>
        <Switch
          id="adblock-enabled"
          checked={s?.adblock_enabled ?? true}
          disabled={!s}
          onCheckedChange={(v) => onChange({ adblock_enabled: v })}
        />
      </div>

      <div className="px-4 py-3">
        <p className="text-sm font-medium" id="popup-policy-label">
          Popup e nuove schede
        </p>
        <div role="radiogroup" aria-labelledby="popup-policy-label" className="mt-2 grid grid-cols-3 gap-1 rounded-xl bg-muted p-1">
          {POLICIES.map((p) => (
            <button
              key={p.value}
              type="button"
              role="radio"
              aria-checked={policy === p.value}
              disabled={!s}
              onClick={() => onChange({ popup_policy: p.value })}
              className={cn(
                "h-9 rounded-lg text-sm font-medium transition-colors",
                policy === p.value ? "bg-background shadow-sm" : "text-muted-foreground",
              )}
            >
              {p.label}
            </button>
          ))}
        </div>
        <p className="mt-1.5 text-xs text-muted-foreground">
          {POLICIES.find((p) => p.value === policy)?.hint} I popup pubblicitari vengono sempre chiusi.
        </p>
      </div>

      <HostList
        label="Siti senza blocco pubblicità"
        empty="Nessuno: il blocco è attivo ovunque."
        hosts={s?.adblock_disabled_hosts ?? []}
        onRemove={(h) => onChange({ adblock_disabled_hosts: (s?.adblock_disabled_hosts ?? []).filter((x) => x !== h) })}
      />
      <HostList
        label="Siti con popup sempre bloccati"
        empty="Nessuno."
        hosts={s?.popup_blocked_hosts ?? []}
        onRemove={(h) => onChange({ popup_blocked_hosts: (s?.popup_blocked_hosts ?? []).filter((x) => x !== h) })}
      />

      <div className="px-4 py-3">
        <div className="flex items-center gap-3">
          <div className="min-w-0 flex-1">
            <p className="text-sm font-medium">Liste filtri</p>
            <p className="text-xs text-muted-foreground tabular-nums">
              {filters.isLoading ? "…" : `${lists.length} liste · ${totalRules.toLocaleString("it-IT")} regole · aggiornate ogni 24 ore`}
            </p>
          </div>
          <Button variant="secondary" size="sm" disabled={refresh.isPending} onClick={() => refresh.mutate()}>
            {refresh.isPending ? <Loader2 className="size-4 animate-spin" /> : <RefreshCw className="size-4" />}
            Aggiorna
          </Button>
        </div>
        {lists.length > 0 && (
          <ul className="mt-2 space-y-1 text-xs text-muted-foreground">
            {lists.map((l) => (
              <li key={l.name} className="flex justify-between gap-2">
                <span className="truncate">{l.name}</span>
                <span className="shrink-0 tabular-nums">
                  {l.rules.toLocaleString("it-IT")}
                  {l.updated_at ? ` · ${formatRelative(l.updated_at)}` : " · inclusa"}
                </span>
              </li>
            ))}
          </ul>
        )}
      </div>
    </>
  );
}
