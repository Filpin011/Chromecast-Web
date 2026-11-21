"use client";

import { MoreVertical, Pencil, Trash2 } from "lucide-react";
import { SiteIcon } from "@/components/favorites/site-tiles";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import type { Favorite } from "@/lib/api/types";
import { useT } from "@/i18n";
import { hostOf } from "@/lib/format";

/** Saved site row: tap opens it in the remote browser (never a cast); overflow menu renames / deletes. */
export function SiteRow({
  site,
  onOpen,
  onRename,
  onDelete,
}: {
  site: Favorite;
  onOpen: () => void;
  onRename: () => void;
  onDelete: () => void;
}) {
  const t = useT();
  return (
    <div className="flex items-center gap-1 rounded-xl transition-colors hover:bg-muted/50">
      <button
        type="button"
        onClick={onOpen}
        aria-label={t("sites.open", { name: site.title })}
        className="flex min-h-16 min-w-0 flex-1 items-center gap-3 rounded-xl px-2 py-2 text-left active:bg-muted"
      >
        <SiteIcon src={site.thumbnail} />
        <span className="min-w-0 flex-1">
          <span className="line-clamp-1 text-sm font-medium">{site.title}</span>
          <span className="line-clamp-1 text-xs text-muted-foreground">{hostOf(site.input)}</span>
        </span>
      </button>
      <DropdownMenu>
        <DropdownMenuTrigger render={<Button variant="ghost" size="icon" aria-label={t("playlists.actionsFor", { name: site.title })} />}>
          <MoreVertical className="size-4" />
        </DropdownMenuTrigger>
        <DropdownMenuContent align="end" className="w-52">
          <DropdownMenuItem onClick={onRename}>
            <Pencil className="size-4" /> {t("favorites.rename")}
          </DropdownMenuItem>
          <DropdownMenuItem variant="destructive" onClick={onDelete}>
            <Trash2 className="size-4" /> {t("common.delete")}
          </DropdownMenuItem>
        </DropdownMenuContent>
      </DropdownMenu>
    </div>
  );
}
