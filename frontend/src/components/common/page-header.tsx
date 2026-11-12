import type { ReactNode } from "react";
import { DeviceButton } from "@/components/devices/device-button";
import { cn } from "@/lib/utils";

/** Sticky, translucent page header (large title on mobile like iOS). */
export function PageHeader({
  title,
  subtitle,
  actions,
  className,
}: {
  title: ReactNode;
  subtitle?: ReactNode;
  actions?: ReactNode;
  className?: string;
}) {
  return (
    <header
      className={cn(
        "sticky top-0 z-30 border-b border-transparent bg-background/80 pt-safe backdrop-blur-xl supports-backdrop-filter:bg-background/65",
        className,
      )}
    >
      <div className="mx-auto flex min-h-14 max-w-5xl items-center gap-2 px-4 py-2 md:px-8 md:py-4">
        <div className="min-w-0 flex-1">
          <h1 className="truncate font-heading text-2xl font-bold tracking-tight md:text-3xl">{title}</h1>
          {subtitle && <p className="truncate text-sm text-muted-foreground">{subtitle}</p>}
        </div>
        {actions}
        <DeviceButton className="md:hidden" />
      </div>
    </header>
  );
}

export function PageBody({ children, className }: { children: ReactNode; className?: string }) {
  return <div className={cn("mx-auto w-full max-w-5xl px-4 pb-chrome md:px-8", className)}>{children}</div>;
}
