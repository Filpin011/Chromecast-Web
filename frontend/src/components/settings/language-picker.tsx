"use client";

import { LOCALE_NATIVE_NAMES, LOCALES, useLocale, useT } from "@/i18n";
import { cn } from "@/lib/utils";

/** Segmented English / Italiano switch (native names); applies instantly and is remembered on this device. */
export function LanguagePicker({ className }: { className?: string }) {
  const t = useT();
  const [locale, setLocale] = useLocale();
  return (
    <div
      role="radiogroup"
      aria-label={t("settings.language")}
      className={cn("grid grid-cols-2 gap-1 rounded-xl bg-muted p-1", className)}
    >
      {LOCALES.map((l) => {
        const active = locale === l;
        return (
          <button
            key={l}
            type="button"
            role="radio"
            lang={l}
            aria-checked={active}
            onClick={() => setLocale(l)}
            className={cn(
              "flex h-9 items-center justify-center rounded-lg text-xs font-medium transition-all",
              active ? "bg-background text-foreground shadow-sm" : "text-muted-foreground hover:text-foreground",
            )}
          >
            {LOCALE_NATIVE_NAMES[l]}
          </button>
        );
      })}
    </div>
  );
}
