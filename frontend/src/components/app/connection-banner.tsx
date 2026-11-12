"use client";

import { AnimatePresence, motion } from "motion/react";
import { WifiOff } from "lucide-react";
import { useEffect, useState } from "react";
import { useConnection } from "@/hooks/use-app-state";
import { useT } from "@/i18n";

/** Small banner shown when the live connection to the server drops (after a grace period). */
export function ConnectionBanner() {
  const tr = useT();
  const connection = useConnection();
  const down = connection === "closed" || connection === "connecting";
  const [show, setShow] = useState(false);
  useEffect(() => {
    if (!down) {
      const t = setTimeout(() => setShow(false), 0);
      return () => clearTimeout(t);
    }
    const t = setTimeout(() => setShow(true), 2500);
    return () => clearTimeout(t);
  }, [down]);
  return (
    <AnimatePresence>
      {show && (
        <motion.div
          role="status"
          initial={{ height: 0, opacity: 0 }}
          animate={{ height: "auto", opacity: 1 }}
          exit={{ height: 0, opacity: 0 }}
          className="overflow-hidden bg-amber-500/15 text-amber-700 dark:text-amber-300"
        >
          <div className="flex items-center justify-center gap-2 px-4 pt-[max(env(safe-area-inset-top),0.5rem)] pb-2 text-xs font-medium">
            <WifiOff className="size-3.5" />
            {tr("connection.lost")}
          </div>
        </motion.div>
      )}
    </AnimatePresence>
  );
}
