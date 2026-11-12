"use client";

import { ExternalLink, ShieldBan, X } from "lucide-react";
import { motion } from "motion/react";
import { Button } from "@/components/ui/button";
import type { PopupDecision, PopupRequest } from "@/lib/api/types";
import { useT } from "@/i18n";
import { hostOf } from "@/lib/format";

/** Compact prompt for a held popup / redirect: "The page wants to open: <host>". */
export function PopupPrompt({
  popup,
  more,
  onDecide,
}: {
  popup: PopupRequest;
  /** Other prompts queued behind this one. */
  more: number;
  onDecide: (decision: PopupDecision) => void;
}) {
  const t = useT();
  const opener = hostOf(popup.opener_url) || t("popup.thisSite");
  return (
    <motion.div
      role="alertdialog"
      aria-label={t("popup.label")}
      initial={{ y: -16, opacity: 0 }}
      animate={{ y: 0, opacity: 1 }}
      exit={{ y: -16, opacity: 0 }}
      transition={{ type: "spring", stiffness: 500, damping: 38 }}
      className="absolute inset-x-2 top-2 z-30 mx-auto max-w-md rounded-2xl border bg-popover/95 p-3 shadow-xl backdrop-blur-xl"
    >
      <div className="flex items-start gap-2">
        <div className="min-w-0 flex-1">
          <p className="text-sm">
            {t("popup.wantsToOpen")} <span className="font-semibold break-all">{popup.host}</span>
          </p>
          <p className="truncate text-xs text-muted-foreground" title={popup.url}>
            {popup.url}
          </p>
        </div>
        {more > 0 && (
          <span className="shrink-0 rounded-full bg-muted px-2 py-0.5 text-xs font-medium tabular-nums">+{more}</span>
        )}
      </div>
      <div className="mt-3 grid grid-cols-2 gap-2">
        <Button size="sm" onClick={() => onDecide("open")}>
          <ExternalLink className="size-4" /> {t("common.open")}
        </Button>
        <Button size="sm" variant="secondary" onClick={() => onDecide("block")}>
          <X className="size-4" /> {t("popup.block")}
        </Button>
        <Button
          size="sm"
          variant="ghost"
          className="col-span-2 text-destructive"
          title={t("popup.alwaysBlockFrom", { host: opener })}
          onClick={() => onDecide("block_always")}
        >
          <ShieldBan className="size-4" /> {t("popup.alwaysBlock")}
        </Button>
      </div>
    </motion.div>
  );
}
