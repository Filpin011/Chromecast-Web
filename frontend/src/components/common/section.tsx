"use client";

import type { LucideIcon } from "lucide-react";
import Link from "next/link";
import type { ReactNode } from "react";
import { useT } from "@/i18n";
import { cn } from "@/lib/utils";

/** A section's title row: muted icon + title, and an optional "See all" link on the right. */
export function SectionHeader({ title, icon: Icon, href }: { title: string; icon: LucideIcon; href?: string }) {
  const t = useT();
  return (
    <div className="flex items-center justify-between px-1">
      <h2 className="flex items-center gap-2 text-sm font-semibold text-muted-foreground">
        <Icon className="size-4" /> {title}
      </h2>
      {href && (
        // 44px touch target; the negative margin keeps the header row at text height
        <Link href={href} className="-my-3 -mr-2 inline-flex min-h-11 items-center px-2 text-sm font-medium text-primary">
          {t("common.seeAll")}
        </Link>
      )}
    </div>
  );
}

/** A titled block of a page (Home, Settings, browser start): `SectionHeader` + its content. */
export function Section({
  title,
  icon,
  href,
  className,
  children,
}: {
  title: string;
  icon: LucideIcon;
  href?: string;
  className?: string;
  children: ReactNode;
}) {
  return (
    <section className={cn("space-y-2", className)}>
      <SectionHeader title={title} icon={icon} href={href} />
      {children}
    </section>
  );
}
