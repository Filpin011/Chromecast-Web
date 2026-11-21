"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { RefreshCw, X } from "lucide-react";
import { Spinner } from "@/components/ui/spinner";
import { toast } from "sonner";
import { SegmentedControl } from "@/components/common/segmented-control";
import { Button } from "@/components/ui/button";
import { Switch } from "@/components/ui/switch";
import { api } from "@/lib/api";
import type { PopupPolicy, Settings } from "@/lib/api/types";
import { formatNumber, useT, type MessageKey } from "@/i18n";
import { formatRelative } from "@/lib/format";
import { errorMessage } from "@/lib/query";

const POLICIES: { value: PopupPolicy; label: MessageKey; hint: MessageKey }[] = [
  { value: "ask", label: "adblock.policy.ask", hint: "adblock.policy.askHint" },
  { value: "block", label: "adblock.policy.block", hint: "adblock.policy.blockHint" },
  { value: "allow", label: "adblock.policy.allow", hint: "adblock.policy.allowHint" },
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
  const t = useT();
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
                aria-label={t("devices.removeName", { name: h })}
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

/** "Browser & ads": global ad-block switch, popup policy, per-site lists, filter lists. */
export function AdblockSettings({ settings: s, onChange }: { settings: Settings | undefined; onChange: (patch: Partial<Settings>) => void }) {
  const t = useT();
  const qc = useQueryClient();
  const filters = useQuery({ queryKey: FILTERS_KEY, queryFn: () => api.filters.list(), staleTime: 60_000 });
  const refresh = useMutation({
    mutationFn: () => api.filters.refresh(),
    onSuccess: (data) => {
      qc.setQueryData(FILTERS_KEY, data);
      toast.success(t("adblock.listsUpdated"));
    },
    onError: (e) => toast.error(errorMessage(e, t("adblock.listsUpdateFailed"))),
  });
  const lists = filters.data?.lists ?? [];
  const totalRules = lists.reduce((n, l) => n + l.rules, 0);
  const policy = s?.popup_policy ?? "ask";

  return (
    <>
      <div className="flex min-h-14 items-center gap-3 px-4 py-3">
        <div className="min-w-0 flex-1">
          <label htmlFor="adblock-enabled" className="block text-sm font-medium">
            {t("adblock.title")}
          </label>
          <p className="text-xs text-muted-foreground">{t("adblock.description")}</p>
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
          {t("adblock.popups")}
        </p>
        <SegmentedControl
          aria-labelledby="popup-policy-label"
          className="mt-2"
          disabled={!s}
          value={policy}
          onChange={(v) => onChange({ popup_policy: v })}
          options={POLICIES.map((p) => ({ value: p.value, label: t(p.label) }))}
        />
        <p className="mt-1.5 text-xs text-muted-foreground">
          {t(POLICIES.find((p) => p.value === policy)?.hint ?? "adblock.policy.askHint")} {t("adblock.adPopupsClosed")}
        </p>
      </div>

      <HostList
        label={t("adblock.disabledHosts")}
        empty={t("adblock.disabledHostsEmpty")}
        hosts={s?.adblock_disabled_hosts ?? []}
        onRemove={(h) => onChange({ adblock_disabled_hosts: (s?.adblock_disabled_hosts ?? []).filter((x) => x !== h) })}
      />
      <HostList
        label={t("adblock.popupBlockedHosts")}
        empty={t("adblock.popupBlockedHostsEmpty")}
        hosts={s?.popup_blocked_hosts ?? []}
        onRemove={(h) => onChange({ popup_blocked_hosts: (s?.popup_blocked_hosts ?? []).filter((x) => x !== h) })}
      />

      <div className="px-4 py-3">
        <div className="flex items-center gap-3">
          <div className="min-w-0 flex-1">
            <p className="text-sm font-medium">{t("adblock.filterLists")}</p>
            <p className="text-xs text-muted-foreground tabular-nums">
              {filters.isLoading ? "…" : `${t.plural("adblock.lists", lists.length)} · ${t.plural("adblock.rules", totalRules)} · ${t("adblock.updatedDaily")}`}
            </p>
          </div>
          <Button variant="secondary" size="sm" disabled={refresh.isPending} onClick={() => refresh.mutate()}>
            {refresh.isPending ? <Spinner /> : <RefreshCw className="size-4" />}
            {t("adblock.refreshLists")}
          </Button>
        </div>
        {lists.length > 0 && (
          <ul className="mt-2 space-y-1 text-xs text-muted-foreground">
            {lists.map((l) => (
              <li key={l.name} className="flex justify-between gap-2">
                <span className="truncate">{l.updated_at === null ? t("adblock.bundledName") : l.name}</span>
                <span className="shrink-0 tabular-nums">
                  {formatNumber(l.rules, undefined, t.locale)}
                  {l.updated_at ? ` · ${formatRelative(l.updated_at)}` : ` · ${t("adblock.bundled")}`}
                </span>
              </li>
            ))}
          </ul>
        )}
      </div>
    </>
  );
}
