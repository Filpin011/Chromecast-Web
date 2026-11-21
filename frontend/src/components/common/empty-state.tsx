import type { LucideIcon } from "lucide-react";
import type { ReactNode } from "react";
import { cn } from "@/lib/utils";
import { IconTile } from "./icon-tile";

export function EmptyState({
  icon,
  title,
  description,
  action,
  className,
  iconClassName,
}: {
  icon: LucideIcon;
  title: string;
  description?: ReactNode;
  action?: ReactNode;
  className?: string;
  /** e.g. `animate-pulse` for a "waiting for something" state. */
  iconClassName?: string;
}) {
  return (
    <div className={cn("flex flex-col items-center justify-center gap-3 px-6 py-14 text-center", className)}>
      <IconTile icon={icon} tone="muted" size="lg" iconClassName={iconClassName} />
      <div className="space-y-1">
        <p className="font-medium">{title}</p>
        {description && <p className="mx-auto max-w-xs text-sm text-muted-foreground">{description}</p>}
      </div>
      {action}
    </div>
  );
}
