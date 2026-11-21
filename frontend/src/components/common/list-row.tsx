"use client";

import { MoreVertical, type LucideIcon } from "lucide-react";
import { Fragment, type ReactNode } from "react";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { cn } from "@/lib/utils";

export interface RowAction {
  label: string;
  icon: LucideIcon;
  onClick: () => void;
  destructive?: boolean;
  /** Draw a separator above this item. */
  separated?: boolean;
}

/** The ⋮ overflow menu of a list row or card: one item per action, destructive ones in red. */
export function RowMenu({ label, actions, className }: { label: string; actions: RowAction[]; className?: string }) {
  if (!actions.length) return null;
  return (
    <DropdownMenu>
      <DropdownMenuTrigger render={<Button variant="ghost" size="icon" aria-label={label} className={className} />}>
        <MoreVertical className="size-4" />
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="w-52">
        {actions.map(({ label: l, icon: Icon, onClick, destructive, separated }) => (
          <Fragment key={l}>
            {separated && <DropdownMenuSeparator />}
            <DropdownMenuItem variant={destructive ? "destructive" : "default"} onClick={onClick}>
              <Icon className="size-4" /> {l}
            </DropdownMenuItem>
          </Fragment>
        ))}
      </DropdownMenuContent>
    </DropdownMenu>
  );
}

/**
 * The app's list row (Library, Home "Recent"): a tappable area with a leading visual, title and
 * subtitle, plus an optional ⋮ menu. Rows sit in a `rounded-2xl border bg-card p-1` list.
 */
export function ListRow({
  leading,
  title,
  subtitle,
  onClick,
  label,
  disabled,
  menuLabel,
  actions = [],
  className,
}: {
  leading: ReactNode;
  title: ReactNode;
  subtitle?: ReactNode;
  onClick: () => void;
  /** Accessible name of the tap area (what the tap does). */
  label: string;
  disabled?: boolean;
  /** Accessible name of the ⋮ button. */
  menuLabel?: string;
  actions?: RowAction[];
  className?: string;
}) {
  return (
    <div className={cn("flex items-center gap-1 rounded-xl transition-colors hover:bg-muted/50", className)}>
      <button
        type="button"
        onClick={onClick}
        disabled={disabled}
        aria-label={label}
        className="flex min-h-16 min-w-0 flex-1 items-center gap-3 rounded-xl px-2 py-2 text-left active:bg-muted"
      >
        {leading}
        <span className="min-w-0 flex-1">
          <span className="line-clamp-1 text-sm font-medium">{title}</span>
          {subtitle && <span className="line-clamp-1 text-xs text-muted-foreground">{subtitle}</span>}
        </span>
      </button>
      {menuLabel && <RowMenu label={menuLabel} actions={actions} />}
    </div>
  );
}

/** Placeholder row while a list loads (same height as `ListRow`). */
export function ListRowSkeleton() {
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
