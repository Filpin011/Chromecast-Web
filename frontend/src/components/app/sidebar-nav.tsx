"use client";

import { Cast } from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { DeviceButton } from "@/components/devices/device-button";
import { useLocalAvailable } from "@/hooks/queries";
import { cn } from "@/lib/utils";
import { isActivePath, NAV_ITEMS } from "./nav-items";
import { ThemeToggle } from "./theme-toggle";

export function SidebarNav() {
  const pathname = usePathname() ?? "/";
  const localAvailable = useLocalAvailable();
  return (
    <aside className="fixed inset-y-0 left-0 z-40 hidden w-(--sidebar-w) flex-col border-r bg-sidebar text-sidebar-foreground md:flex">
      <div className="flex h-16 items-center gap-2.5 px-5">
        <div className="grid size-9 place-items-center rounded-xl bg-gradient-to-br from-primary to-indigo-700 text-white shadow-md shadow-primary/30">
          <Cast className="size-5" />
        </div>
        <span className="font-heading text-lg font-semibold tracking-tight">Chromecast Web</span>
      </div>
      <nav aria-label="Navigazione principale" className="flex-1 space-y-1 px-3 py-2">
        {NAV_ITEMS.filter((i) => !i.requiresLocal || localAvailable).map((item) => {
          const active = isActivePath(pathname, item.href);
          const Icon = item.icon;
          return (
            <Link
              key={item.href}
              href={item.href}
              aria-current={active ? "page" : undefined}
              className={cn(
                "flex h-11 items-center gap-3 rounded-xl px-3 text-sm font-medium transition-colors",
                active
                  ? "bg-sidebar-accent text-sidebar-accent-foreground"
                  : "text-muted-foreground hover:bg-sidebar-accent/60 hover:text-sidebar-foreground",
              )}
            >
              <Icon className={cn("size-5", active && "text-primary")} />
              {item.label}
            </Link>
          );
        })}
      </nav>
      <div className="space-y-2 border-t p-3">
        <DeviceButton showName />
        <ThemeToggle />
      </div>
    </aside>
  );
}
