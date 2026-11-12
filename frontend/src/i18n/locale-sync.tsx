"use client";

import { useEffect, useLayoutEffect } from "react";
import { detectLocale, isLocale, LOCALE_STORAGE_KEY, useLocaleStore } from "./index";
import { LOCALE_PENDING_CLASS } from "./locale-bootstrap";

// useLayoutEffect warns during SSR/static export; fall back to useEffect there.
const useIsoLayoutEffect = typeof window !== "undefined" ? useLayoutEffect : useEffect;

/**
 * Applies the saved / browser language before the first paint (the static HTML is English; the
 * inline bootstrap script in the root layout keeps it hidden until then when the locale isn't
 * English), keeps `<html lang>` in sync with the current locale and follows language changes made
 * in other tabs / windows.
 */
export function LocaleSync() {
  const locale = useLocaleStore((s) => s.locale);
  useIsoLayoutEffect(() => {
    useLocaleStore.getState().hydrate();
  }, []);
  useIsoLayoutEffect(() => {
    const root = document.documentElement;
    root.lang = locale;
    // reveal once this render shows the hydrated locale (the bootstrap script hid it until then)
    const { hydrated, locale: current } = useLocaleStore.getState();
    if (hydrated && current === locale) root.classList.remove(LOCALE_PENDING_CLASS);
  }, [locale]);
  useEffect(() => {
    const onStorage = (e: StorageEvent) => {
      if (e.key !== LOCALE_STORAGE_KEY && e.key !== null) return;
      // another tab picked a language (or cleared storage): follow it without writing it back
      const next = isLocale(e.newValue) ? e.newValue : detectLocale(null);
      useLocaleStore.setState({ locale: next, hydrated: true });
    };
    window.addEventListener("storage", onStorage);
    return () => window.removeEventListener("storage", onStorage);
  }, []);
  return null;
}
