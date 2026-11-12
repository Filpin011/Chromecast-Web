"use client";

import { Compass, Plus, X } from "lucide-react";
import Link from "next/link";
import { isActivePath, NAV_ITEMS } from "@/components/app/nav-items";
import { Button } from "@/components/ui/button";
import { Drawer, DrawerContent, DrawerTitle } from "@/components/ui/drawer";
import { useLocalAvailable } from "@/hooks/queries";
import type { BrowserSession } from "@/lib/api/types";
import { LanguagePicker } from "@/components/settings/language-picker";
import { useT } from "@/i18n";
import { hostOf } from "@/lib/format";
import { cn } from "@/lib/utils";

const LIST = "overflow-y-auto px-3 pb-[max(env(safe-area-inset-bottom),1rem)]";

/**
 * App navigation while the remote browser is open (the phone tab bar is hidden there).
 * The session keeps running on the server: it can be resumed from the Browser screen.
 */
export function AppMenuSheet({ open, onOpenChange }: { open: boolean; onOpenChange: (open: boolean) => void }) {
  const t = useT();
  const localAvailable = useLocalAvailable();
  return (
    <Drawer open={open} onOpenChange={onOpenChange} showSwipeHandle>
      <DrawerContent>
        <DrawerTitle className="px-5 pt-3 pb-2">{t("browser.goTo")}</DrawerTitle>
        <nav aria-label={t("browser.appMenu")} className={LIST}>
          {NAV_ITEMS.filter((i) => !i.requiresLocal || localAvailable).map((item) => {
            const Icon = item.icon;
            const here = isActivePath("/browser/", item.href);
            return (
              <Link
                key={item.href}
                href={item.href}
                onClick={() => onOpenChange(false)}
                aria-current={here ? "page" : undefined}
                className={cn(
                  "flex min-h-12 items-center gap-3 rounded-xl px-3 text-sm font-medium",
                  here ? "bg-primary/10 text-primary" : "active:bg-muted",
                )}
              >
                <Icon className="size-5" />
                {t(item.label)}
              </Link>
            );
          })}
          <div className="px-1 pt-3">
            <LanguagePicker />
          </div>
        </nav>
      </DrawerContent>
    </Drawer>
  );
}

/** Open remote-browser sessions ("tabs"): switch, close, or start a new one. */
export function SessionsSheet({
  open,
  onOpenChange,
  sessions,
  currentId,
  onSwitch,
  onClose,
  onNew,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  sessions: BrowserSession[];
  currentId: string;
  onSwitch: (s: BrowserSession) => void;
  onClose: (s: BrowserSession) => void;
  onNew: () => void;
}) {
  const t = useT();
  return (
    <Drawer open={open} onOpenChange={onOpenChange} showSwipeHandle>
      <DrawerContent>
        <DrawerTitle className="px-5 pt-3 pb-2">{t("browser.openSessions")}</DrawerTitle>
        <ul className={cn(LIST, "space-y-2")} aria-label={t("browser.openSessions")}>
          {sessions.map((s) => {
            const current = s.id === currentId;
            return (
              <li key={s.id} className={cn("flex items-center gap-1 rounded-2xl border bg-card", current && "border-primary/60")}>
                <button
                  type="button"
                  onClick={() => {
                    onOpenChange(false);
                    if (!current) onSwitch(s);
                  }}
                  aria-current={current ? "true" : undefined}
                  className="flex min-h-14 min-w-0 flex-1 items-center gap-3 px-4 text-left"
                >
                  <Compass className={cn("size-5 shrink-0", current ? "text-primary" : "text-muted-foreground")} />
                  <span className="min-w-0">
                    <span className="block truncate text-sm font-medium">{s.title || hostOf(s.url)}</span>
                    <span className="block truncate text-xs text-muted-foreground">
                      {hostOf(s.url)} · {t.plural("browser.streamCount", s.captured.length)}
                    </span>
                  </span>
                </button>
                <Button variant="ghost" size="icon" aria-label={t("common.closeName", { name: hostOf(s.url) })} onClick={() => onClose(s)} className="mr-1">
                  <X className="size-4" />
                </Button>
              </li>
            );
          })}
          <li>
            <Button
              variant="secondary"
              size="lg"
              className="w-full gap-2"
              onClick={() => {
                onOpenChange(false);
                onNew();
              }}
            >
              <Plus className="size-4" /> {t("browser.newSession")}
            </Button>
          </li>
        </ul>
      </DrawerContent>
    </Drawer>
  );
}
