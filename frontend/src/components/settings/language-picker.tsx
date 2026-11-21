"use client";

import { SegmentedControl, type SegmentSize } from "@/components/common/segmented-control";
import { LOCALE_NATIVE_NAMES, LOCALES, useLocale, useT } from "@/i18n";

/** Segmented English / Italiano switch (native names); applies instantly and is remembered on this device. */
export function LanguagePicker({ className, size }: { className?: string; size?: SegmentSize }) {
  const t = useT();
  const [locale, setLocale] = useLocale();
  return (
    <SegmentedControl
      aria-label={t("settings.language")}
      className={className}
      size={size}
      value={locale}
      onChange={setLocale}
      options={LOCALES.map((l) => ({ value: l, label: LOCALE_NATIVE_NAMES[l], lang: l }))}
    />
  );
}
