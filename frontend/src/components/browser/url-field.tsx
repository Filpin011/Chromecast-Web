"use client";

import { Globe, Lock, RotateCw } from "lucide-react";
import { useState, type FormEvent } from "react";
import { useT } from "@/i18n";
import { hostOf } from "@/lib/format";
import { normalizeUrl } from "@/lib/url";
import { cn } from "@/lib/utils";

/**
 * Compact URL pill: shows the host (tap to edit) with the reload control inside it. Below 400px the reload
 * control is hidden so the host stays readable; the workspace offers it in the "More" menu there.
 */
export function UrlField({
  url,
  onNavigate,
  onReload,
}: {
  url: string;
  onNavigate: (url: string) => void;
  onReload?: () => void;
}) {
  const t = useT();
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(url);
  const secure = url.startsWith("https:");
  const submit = (e: FormEvent) => {
    e.preventDefault();
    const u = normalizeUrl(draft);
    if (u) onNavigate(u);
    setEditing(false);
  };
  if (editing) {
    return (
      <form onSubmit={submit} className="min-w-0 flex-1">
        <input
          autoFocus
          aria-label={t("url.address")}
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          onBlur={() => setEditing(false)}
          onFocus={(e) => e.currentTarget.select()}
          inputMode="url"
          enterKeyHint="go"
          autoCapitalize="off"
          autoCorrect="off"
          spellCheck={false}
          className="h-11 w-full rounded-full bg-muted px-4 text-base outline-none focus:ring-2 focus:ring-primary/40"
        />
      </form>
    );
  }
  return (
    <div className="flex h-11 min-w-0 flex-1 items-center rounded-full bg-muted">
      <button
        type="button"
        onClick={() => {
          setDraft(url);
          setEditing(true);
        }}
        className={cn(
          "flex h-full min-w-0 flex-1 items-center justify-center gap-1.5 rounded-full px-3 text-sm",
          onReload && "min-[400px]:pr-0",
        )}
        aria-label={t("url.addressEdit", { url })}
      >
        {secure ? <Lock className="size-3.5 shrink-0 text-muted-foreground" /> : <Globe className="size-3.5 shrink-0 text-muted-foreground" />}
        <span className="truncate font-medium">{hostOf(url) || t("url.newPage")}</span>
      </button>
      {onReload && (
        <button
          type="button"
          onClick={onReload}
          aria-label={t("common.reload")}
          className="hidden size-11 shrink-0 place-items-center rounded-full text-muted-foreground active:bg-foreground/10 min-[400px]:grid"
        >
          <RotateCw className="size-4.5" />
        </button>
      )}
    </div>
  );
}
