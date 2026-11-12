"use client";

import { useEffect, useState } from "react";

/** Re-render every `intervalMs` while `enabled`, returning the current clock. */
export function useNow(intervalMs = 500, enabled = true): number {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    if (!enabled) return;
    const t = setInterval(() => setNow(Date.now()), intervalMs);
    return () => clearInterval(t);
  }, [intervalMs, enabled]);
  return now;
}
