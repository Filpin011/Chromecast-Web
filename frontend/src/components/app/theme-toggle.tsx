"use client";

import { Monitor, Moon, Sun } from "lucide-react";
import { useTheme } from "next-themes";
import { useSyncExternalStore } from "react";
import { SegmentedControl, type SegmentSize } from "@/components/common/segmented-control";
import { useT } from "@/i18n";

type ThemeValue = "light" | "dark" | "system";

function useMounted() {
  return useSyncExternalStore(
    () => () => {},
    () => true,
    () => false,
  );
}

/** Segmented light / dark / system switch. */
export function ThemeToggle({ className, size }: { className?: string; size?: SegmentSize }) {
  const t = useT();
  const { theme, setTheme } = useTheme();
  const mounted = useMounted();
  return (
    <SegmentedControl<ThemeValue>
      aria-label={t("theme.label")}
      className={className}
      size={size}
      value={mounted ? ((theme as ThemeValue | undefined) ?? null) : null}
      onChange={setTheme}
      options={[
        { value: "light", label: t("theme.light"), icon: Sun },
        { value: "dark", label: t("theme.dark"), icon: Moon },
        { value: "system", label: t("theme.system"), icon: Monitor },
      ]}
    />
  );
}
