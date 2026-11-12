"use client";

import { Shield, ShieldCheck, ShieldOff, Square } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Switch } from "@/components/ui/switch";
import { useT } from "@/i18n";
import { hostOf } from "@/lib/format";
import { cn } from "@/lib/utils";

/** Compact count for the badge: 0..99, then "99+". */
export function blockedBadge(count: number): string | null {
  if (!count || count < 0) return null;
  return count > 99 ? "99+" : String(count);
}

/**
 * uBlock-Origin-style shield: badge with the blocked requests of the current page, and the big
 * per-site "power button" ("Ad blocking on for this site").
 */
export function AdblockButton({
  url,
  enabled,
  blocked,
  busy,
  onToggle,
  onStopMedia,
}: {
  url: string;
  enabled: boolean;
  blocked: number;
  busy?: boolean;
  onToggle: (enabled: boolean) => void;
  onStopMedia: () => void;
}) {
  const t = useT();
  const badge = enabled ? blockedBadge(blocked) : null;
  const host = hostOf(url) || url;
  return (
    <DropdownMenu>
      <DropdownMenuTrigger
        render={
          <Button
            variant="ghost"
            size="icon"
            className="relative shrink-0"
            aria-label={enabled ? t.plural("adblock.buttonOn", blocked) : t("adblock.buttonOff")}
          />
        }
      >
        {enabled ? <ShieldCheck className="size-5 text-primary" /> : <ShieldOff className="size-5 text-muted-foreground" />}
        {badge && (
          <span
            data-testid="blocked-badge"
            className="absolute -top-0.5 -right-0.5 min-w-4 rounded-full bg-destructive px-1 text-center text-[0.6rem] leading-4 font-bold text-white tabular-nums"
          >
            {badge}
          </span>
        )}
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="w-72 p-0">
        <div className="flex flex-col items-center gap-2 px-4 pt-4 pb-3 text-center">
          <button
            type="button"
            disabled={busy}
            aria-pressed={enabled}
            aria-label={enabled ? t("adblock.disableSite") : t("adblock.enableSite")}
            onClick={() => onToggle(!enabled)}
            className={cn(
              "grid size-16 place-items-center rounded-full border-4 transition-colors disabled:opacity-60",
              enabled ? "border-primary bg-primary/15 text-primary" : "border-muted-foreground/40 text-muted-foreground",
            )}
          >
            <Shield className="size-7" />
          </button>
          <p className="truncate text-sm font-semibold" title={host}>
            {host}
          </p>
          <p className="text-xs text-muted-foreground tabular-nums">
            {enabled ? t.plural("adblock.blockedOnPage", blocked) : t("adblock.noBlockingSite")}
          </p>
        </div>
        <div className="flex items-center gap-3 border-t px-4 py-3">
          <label htmlFor="adblock-site" className="min-w-0 flex-1 text-sm">
            {t("adblock.siteSwitch")}
          </label>
          <Switch id="adblock-site" checked={enabled} disabled={busy} onCheckedChange={(v) => onToggle(v)} />
        </div>
        <DropdownMenuSeparator className="my-0" />
        <DropdownMenuItem className="m-1" onClick={onStopMedia}>
          <Square className="size-4" /> {t("adblock.stopMedia")}
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
