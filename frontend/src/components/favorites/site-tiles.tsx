"use client";

import { Globe } from "lucide-react";
import { Thumb } from "@/components/common/thumb";
import type { Favorite } from "@/lib/api/types";
import { useT } from "@/i18n";
import { hostOf } from "@/lib/format";
import { cn } from "@/lib/utils";

/** Site icon (favicon) with a globe fallback. */
export function SiteIcon({ src, className }: { src: string | null; className?: string }) {
  return <Thumb src={src} icon={Globe} fit="contain" className={cn("size-10 rounded-xl bg-muted", className)} />;
}

/** Compact quick-access tiles for saved sites: icon + name, tap opens the site in the remote browser. */
export function SiteTiles({ sites, onOpen, className }: { sites: Favorite[]; onOpen: (url: string) => void; className?: string }) {
  const t = useT();
  return (
    <ul className={cn("grid grid-cols-4 gap-2 sm:grid-cols-6", className)}>
      {sites.map((s) => (
        <li key={s.id} className="min-w-0">
          <button
            type="button"
            onClick={() => onOpen(s.input)}
            aria-label={t("sites.open", { name: s.title })}
            title={s.input}
            className="flex w-full flex-col items-center gap-1.5 rounded-2xl px-1 py-2 text-center active:scale-[0.97] active:bg-muted"
          >
            <SiteIcon src={s.thumbnail} className="size-12 border bg-card" />
            <span className="line-clamp-1 w-full text-xs font-medium">{s.title || hostOf(s.input)}</span>
          </button>
        </li>
      ))}
    </ul>
  );
}
