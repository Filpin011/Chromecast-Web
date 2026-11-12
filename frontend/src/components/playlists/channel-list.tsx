"use client";

import { useWindowVirtualizer } from "@tanstack/react-virtual";
import { Cast, Eye, ListPlus, MoreVertical, Star, Tv } from "lucide-react";
import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { Thumb } from "@/components/common/thumb";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuGroup,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import type { Channel } from "@/lib/api/types";
import type { ChannelLayout } from "@/lib/channels";
import { cn } from "@/lib/utils";

export type { ChannelLayout } from "@/lib/channels";

/** Secondary per-channel actions (the tap itself casts right away). */
export type ChannelAction = "queue" | "favorite" | "preview";

const ACTIONS: { action: ChannelAction; label: string; icon: typeof Cast }[] = [
  { action: "queue", label: "Aggiungi alla coda", icon: ListPlus },
  { action: "favorite", label: "Aggiungi ai preferiti", icon: Star },
  { action: "preview", label: "Anteprima", icon: Eye },
];

/**
 * One channel: tap casts; the ⋮ button (or a long-press / right-click, which fires `contextmenu`)
 * opens the secondary actions. The two buttons are siblings — a button can't contain another.
 */
function ChannelItem({
  channel: ch,
  layout,
  disabled,
  onSelect,
  onAction,
}: {
  channel: Channel;
  layout: ChannelLayout;
  disabled?: boolean;
  onSelect: (c: Channel) => void;
  onAction?: (action: ChannelAction, c: Channel) => void;
}) {
  const [menuOpen, setMenuOpen] = useState(false);
  const grid = layout === "grid";
  return (
    <div
      role="listitem"
      className={cn("relative min-w-0", !grid && "flex items-center")}
      onContextMenu={
        onAction
          ? (e) => {
              e.preventDefault();
              setMenuOpen(true);
            }
          : undefined
      }
    >
      {grid ? (
        <button
          type="button"
          disabled={disabled}
          onClick={() => onSelect(ch)}
          title={ch.name}
          className="flex w-full min-w-0 flex-col items-center gap-1 rounded-2xl p-1 text-center transition active:scale-95"
        >
          <Thumb src={ch.logo} icon={Tv} fit="contain" className="aspect-square w-full rounded-2xl bg-card ring-1 ring-border" />
          <span className="line-clamp-2 w-full text-[0.7rem] leading-tight font-medium break-words">{ch.name}</span>
        </button>
      ) : (
        <button
          type="button"
          disabled={disabled}
          onClick={() => onSelect(ch)}
          className="flex h-16 min-w-0 flex-1 items-center gap-3 rounded-xl px-2 text-left active:bg-muted"
        >
          <Thumb src={ch.logo} icon={Tv} fit="contain" className="size-11 rounded-xl bg-card ring-1 ring-border" />
          <span className="min-w-0 flex-1">
            <span className="block truncate text-sm font-medium">{ch.name}</span>
            {ch.group && <span className="block truncate text-xs text-muted-foreground">{ch.group}</span>}
          </span>
        </button>
      )}
      {onAction && (
        <DropdownMenu open={menuOpen} onOpenChange={setMenuOpen}>
          <DropdownMenuTrigger
            aria-label={`Altre azioni per ${ch.name}`}
            className={cn(
              "grid shrink-0 place-items-center text-muted-foreground outline-none focus-visible:ring-2 focus-visible:ring-ring",
              grid
                ? "absolute top-1 right-1 size-8 rounded-full bg-background/70 backdrop-blur"
                : "size-11 rounded-xl active:bg-muted",
            )}
          >
            <MoreVertical className="size-4" />
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end" className="w-56">
            <DropdownMenuGroup>
              <DropdownMenuLabel className="truncate">{ch.name}</DropdownMenuLabel>
              <DropdownMenuItem disabled={disabled} onClick={() => onSelect(ch)}>
                <Cast className="size-4" /> Trasmetti ora
              </DropdownMenuItem>
              {ACTIONS.map(({ action, label, icon: Icon }) => (
                // queueing goes through the same busy cast pipeline; favorite/preview don't
                <DropdownMenuItem key={action} disabled={action === "queue" && disabled} onClick={() => onAction(action, ch)}>
                  <Icon className="size-4" /> {label}
                </DropdownMenuItem>
              ))}
            </DropdownMenuGroup>
          </DropdownMenuContent>
        </DropdownMenu>
      )}
    </div>
  );
}

function useWidth<T extends HTMLElement>() {
  const ref = useRef<T>(null);
  const [width, setWidth] = useState(0);
  useLayoutEffect(() => {
    const el = ref.current;
    if (!el) return;
    setWidth(el.clientWidth);
    const ro = new ResizeObserver(([e]) => setWidth(e.contentRect.width));
    ro.observe(el);
    return () => ro.disconnect();
  }, []);
  return { ref, width };
}

export function columnsFor(width: number): number {
  if (width >= 1000) return 6;
  if (width >= 760) return 5;
  if (width >= 560) return 4;
  return 3;
}

/**
 * Window-virtualized channel grid/list for thousands of entries.
 * `getItem(i)` may return undefined for not-yet-loaded indexes (rendered as skeletons) — `onNeedMore` is
 * called when the user scrolls near the loaded end.
 */
export function ChannelList({
  total,
  loaded,
  getItem,
  layout,
  onSelect,
  onAction,
  onNeedMore,
  disabled,
}: {
  total: number;
  loaded: number;
  getItem: (index: number) => Channel | undefined;
  layout: ChannelLayout;
  onSelect: (c: Channel) => void;
  onAction?: (action: ChannelAction, c: Channel) => void;
  onNeedMore: () => void;
  disabled?: boolean;
}) {
  const { ref, width } = useWidth<HTMLDivElement>();
  const cols = layout === "grid" ? columnsFor(width || 360) : 1;
  const rows = Math.ceil(total / cols);
  const rowHeight = layout === "grid" ? Math.round((width || 360) / cols) + 40 : 64;
  const [margin, setMargin] = useState(0);
  useLayoutEffect(() => {
    setMargin(ref.current?.offsetTop ?? 0);
  }, [ref, layout]);

  const virtualizer = useWindowVirtualizer({
    count: rows,
    estimateSize: () => rowHeight,
    overscan: 6,
    scrollMargin: margin,
  });
  const items = virtualizer.getVirtualItems();
  const lastRow = items.length ? items[items.length - 1].index : 0;

  useEffect(() => {
    if ((lastRow + 1) * cols >= loaded - cols * 4 && loaded < total) onNeedMore();
  }, [lastRow, cols, loaded, total, onNeedMore]);

  useEffect(() => {
    virtualizer.measure();
  }, [rowHeight, virtualizer]);

  return (
    <div ref={ref} className="relative w-full" style={{ height: virtualizer.getTotalSize() }} role="list" aria-label="Canali">
      {items.map((row) => (
        <div
          key={row.key}
          className={cn("absolute inset-x-0 top-0", layout === "grid" && "grid gap-2")}
          style={{
            transform: `translateY(${row.start - virtualizer.options.scrollMargin}px)`,
            height: row.size,
            gridTemplateColumns: layout === "grid" ? `repeat(${cols}, minmax(0, 1fr))` : undefined,
          }}
        >
          {Array.from({ length: cols }, (_, c) => {
            const index = row.index * cols + c;
            if (index >= total) return null;
            const ch = getItem(index);
            if (!ch) {
              return layout === "grid" ? (
                <div key={c} className="m-0.5 animate-pulse rounded-2xl bg-muted" />
              ) : (
                <div key={c} className="flex h-16 items-center gap-3 px-2">
                  <div className="size-11 animate-pulse rounded-xl bg-muted" />
                  <div className="h-3.5 w-1/2 animate-pulse rounded bg-muted" />
                </div>
              );
            }
            return <ChannelItem key={ch.id} channel={ch} layout={layout} disabled={disabled} onSelect={onSelect} onAction={onAction} />;
          })}
        </div>
      ))}
    </div>
  );
}
