"use client";

import { ListPlus, MoreVertical, Play, Star, Trash2 } from "lucide-react";
import type { ReactNode } from "react";
import { Thumb } from "@/components/common/thumb";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";

export interface MediaRowProps {
  title: string;
  subtitle?: ReactNode;
  thumbnail: string | null;
  onCast: () => void;
  onQueue?: () => void;
  onFavorite?: () => void;
  onDelete?: () => void;
  disabled?: boolean;
}

/** Tappable list row (tap = cast) with an overflow menu for secondary actions. */
export function MediaRow({ title, subtitle, thumbnail, onCast, onQueue, onFavorite, onDelete, disabled }: MediaRowProps) {
  const hasMenu = onQueue || onFavorite || onDelete;
  return (
    <div className="flex items-center gap-1 rounded-xl transition-colors hover:bg-muted/50">
      <button
        type="button"
        onClick={onCast}
        disabled={disabled}
        aria-label={`Trasmetti ${title}`}
        className="flex min-h-16 min-w-0 flex-1 items-center gap-3 rounded-xl px-2 py-2 text-left active:bg-muted"
      >
        <div className="relative">
          <Thumb src={thumbnail} alt="" className="aspect-video h-12" />
          <span className="absolute inset-0 grid place-items-center rounded-lg bg-black/0 text-white opacity-0 transition group-hover:opacity-100">
            <Play className="size-4" fill="currentColor" />
          </span>
        </div>
        <span className="min-w-0 flex-1">
          <span className="line-clamp-1 text-sm font-medium">{title}</span>
          {subtitle && <span className="line-clamp-1 text-xs text-muted-foreground">{subtitle}</span>}
        </span>
      </button>
      {hasMenu && (
        <DropdownMenu>
          <DropdownMenuTrigger render={<Button variant="ghost" size="icon" aria-label={`Azioni per ${title}`} />}>
            <MoreVertical className="size-4" />
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end" className="w-52">
            {onQueue && (
              <DropdownMenuItem onClick={onQueue}>
                <ListPlus className="size-4" /> Aggiungi alla coda
              </DropdownMenuItem>
            )}
            {onFavorite && (
              <DropdownMenuItem onClick={onFavorite}>
                <Star className="size-4" /> Aggiungi ai preferiti
              </DropdownMenuItem>
            )}
            {onDelete && (
              <DropdownMenuItem variant="destructive" onClick={onDelete}>
                <Trash2 className="size-4" /> Elimina
              </DropdownMenuItem>
            )}
          </DropdownMenuContent>
        </DropdownMenu>
      )}
    </div>
  );
}

export function MediaRowSkeleton() {
  return (
    <div className="flex items-center gap-3 px-2 py-2">
      <div className="aspect-video h-12 animate-pulse rounded-lg bg-muted" />
      <div className="flex-1 space-y-2">
        <div className="h-3.5 w-2/3 animate-pulse rounded bg-muted" />
        <div className="h-3 w-1/3 animate-pulse rounded bg-muted" />
      </div>
    </div>
  );
}
