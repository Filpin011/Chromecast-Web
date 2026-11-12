"use client";

import { motion } from "motion/react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useT } from "@/i18n";
import { haptic } from "@/lib/haptics";
import { cn } from "@/lib/utils";
import { isActivePath, NAV_ITEMS } from "./nav-items";

export function BottomTabBar() {
  const t = useT();
  const pathname = usePathname() ?? "/";
  return (
    <nav
      aria-label={t("nav.main")}
      className="fixed inset-x-0 bottom-0 z-40 border-t bg-background/85 pb-safe backdrop-blur-xl supports-backdrop-filter:bg-background/70 md:hidden"
    >
      <ul className="grid h-16 grid-cols-5">
        {NAV_ITEMS.filter((i) => i.tab).map((item) => {
          const active = isActivePath(pathname, item.href);
          const Icon = item.icon;
          return (
            <li key={item.href}>
              <Link
                href={item.href}
                onClick={() => haptic(6)}
                aria-current={active ? "page" : undefined}
                className={cn(
                  "relative flex h-full flex-col items-center justify-center gap-1 text-[0.68rem] font-medium transition-colors",
                  active ? "text-primary" : "text-muted-foreground active:text-foreground",
                )}
              >
                {active && (
                  <motion.span
                    layoutId="tab-pill"
                    className="absolute top-1.5 h-8 w-14 rounded-full bg-primary/12"
                    transition={{ type: "spring", stiffness: 500, damping: 38 }}
                  />
                )}
                <Icon className="relative size-[1.35rem]" strokeWidth={active ? 2.4 : 2} />
                <span className="relative">{t(item.label)}</span>
              </Link>
            </li>
          );
        })}
      </ul>
    </nav>
  );
}
