import { Loader2, type LucideIcon } from "lucide-react";
import type { ReactNode } from "react";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

/**
 * The one overlay drawn over a video / remote-page surface (always dark, whatever the theme): a spinner
 * or an icon, an optional message and an optional action (Retry, Reopen…).
 *
 * - `tone`: `clear` = no backdrop and click-through (loading over a poster), `dim` = darkened content
 *   behind (reconnecting, session lost), `solid` = black (the video failed and is hidden).
 * - `size`: `sm` for preview-sized boxes (players, dialogs), `default` for a full-screen surface.
 */
export function MediaOverlay({
  icon: Icon,
  spinner = false,
  message,
  action,
  tone = "clear",
  size = "default",
  role,
  className,
}: {
  icon?: LucideIcon;
  spinner?: boolean;
  message?: ReactNode;
  action?: { label: string; icon?: LucideIcon; onClick: () => void };
  tone?: "clear" | "dim" | "solid";
  size?: "sm" | "default";
  role?: "status" | "alert";
  className?: string;
}) {
  const sm = size === "sm";
  const iconClass = sm ? "size-6" : "size-7";
  const ActionIcon = action?.icon;
  return (
    <div
      role={role}
      className={cn(
        "absolute inset-0 grid place-items-center text-center text-white/80",
        sm ? "p-4 text-xs" : "px-6 text-sm",
        tone === "clear" && "pointer-events-none",
        tone === "dim" && "bg-black/65",
        tone === "solid" && "bg-black",
        className,
      )}
    >
      <div className={cn("flex flex-col items-center", sm ? "gap-2" : "gap-3")}>
        {spinner ? <Loader2 className={cn(iconClass, "animate-spin")} /> : Icon && <Icon className={iconClass} />}
        {message}
        {action &&
          (sm ? (
            <button
              type="button"
              onClick={action.onClick}
              className="mt-1 inline-flex h-9 items-center gap-1.5 rounded-full bg-white/15 px-4 text-xs font-medium text-white active:bg-white/25"
            >
              {ActionIcon && <ActionIcon className="size-3.5" />} {action.label}
            </button>
          ) : (
            <Button variant="secondary" size="lg" onClick={action.onClick} className="gap-2">
              {ActionIcon && <ActionIcon className="size-4" />} {action.label}
            </Button>
          ))}
      </div>
    </div>
  );
}

/** A black 16:9 box holding only an overlay (a preview that is still resolving, or unavailable). */
export function MediaBox({ className, children }: { className?: string; children: ReactNode }) {
  return <div className={cn("relative aspect-video overflow-hidden rounded-xl bg-black", className)}>{children}</div>;
}
