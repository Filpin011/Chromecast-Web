"use client";

import { SearchX } from "lucide-react";
import Link from "next/link";
import { EmptyState } from "@/components/common/empty-state";
import { PageBody } from "@/components/common/page-header";
import { buttonVariants } from "@/components/ui/button";
import { useT } from "@/i18n";

/** Unknown route: the app's own empty state (translated, themed) instead of Next's built-in 404. */
export default function NotFound() {
  const t = useT();
  return (
    <PageBody className="pt-[calc(env(safe-area-inset-top)+2rem)]">
      <EmptyState
        icon={SearchX}
        title={t("notFound.title")}
        description={t("notFound.hint")}
        action={
          <Link href="/" className={buttonVariants()}>
            {t("notFound.home")}
          </Link>
        }
      />
    </PageBody>
  );
}
