import { useMemo } from "react";
import { create } from "zustand";
import { readStorage, writeStorage } from "@/lib/storage";
import { en, type MessageKey, type Messages } from "./en";
import { it } from "./it";

export type { MessageKey, Messages } from "./en";

export const LOCALES = ["en", "it"] as const;
export type Locale = (typeof LOCALES)[number];
export const DEFAULT_LOCALE: Locale = "en";
export const LOCALE_STORAGE_KEY = "cw.locale";

/** Each language's name written in that language (for the picker). */
export const LOCALE_NATIVE_NAMES: Record<Locale, string> = { en: "English", it: "Italiano" };

const DICTIONARIES: Record<Locale, Messages> = { en, it };

export type Params = Record<string, string | number>;

/** Keys that have plural forms (`<base>_one` / `<base>_other`, plus optional `_zero`/`_few`/`_many`). */
export type PluralKey = {
  [K in MessageKey]: K extends `${infer B}_other` ? B : never;
}[MessageKey];

export function isLocale(v: unknown): v is Locale {
  return typeof v === "string" && (LOCALES as readonly string[]).includes(v);
}

/** saved choice → browser language starting with "it" → English. */
export function detectLocale(
  saved: string | null = readStorage(LOCALE_STORAGE_KEY),
  languages: readonly string[] = typeof navigator !== "undefined"
    ? (navigator.languages?.length ? navigator.languages : [navigator.language])
    : [],
): Locale {
  if (isLocale(saved)) return saved;
  const first = languages.find(Boolean) ?? "";
  return first.toLowerCase().startsWith("it") ? "it" : DEFAULT_LOCALE;
}

/** Replace `{name}` placeholders; unknown placeholders are left as they are. */
export function interpolate(template: string, params?: Params): string {
  if (!params) return template;
  return template.replace(/\{(\w+)\}/g, (m, name: string) =>
    name in params ? String(params[name]) : m,
  );
}

export interface Translator {
  (key: MessageKey, params?: Params): string;
  /** Plural-aware lookup: `{count}` is always available as a parameter. */
  plural: (key: PluralKey, count: number, params?: Params) => string;
  /** Translate a key only known at runtime (e.g. an API error code); `undefined` if it doesn't exist. */
  maybe: (key: string, params?: Params) => string | undefined;
  locale: Locale;
}

function lookup(locale: Locale, key: string): string | undefined {
  const dict = DICTIONARIES[locale] as Record<string, string>;
  return dict[key] ?? (en as Record<string, string>)[key];
}

function makeTranslator(locale: Locale): Translator {
  const nf = new Intl.NumberFormat(locale);
  const rules = new Intl.PluralRules(locale);
  const t = ((key: MessageKey, params?: Params) => interpolate(lookup(locale, key) ?? key, params)) as Translator;
  t.plural = (key, count, params) => {
    const all = { count: nf.format(count), ...params };
    const exact = count === 0 ? lookup(locale, `${key}_zero`) : undefined;
    const tpl = exact ?? lookup(locale, `${key}_${rules.select(count)}`) ?? lookup(locale, `${key}_other`) ?? key;
    return interpolate(tpl, all);
  };
  t.maybe = (key, params) => {
    const v = lookup(locale, key);
    return v === undefined ? undefined : interpolate(v, params);
  };
  t.locale = locale;
  return t;
}

const TRANSLATORS: Record<Locale, Translator> = { en: makeTranslator("en"), it: makeTranslator("it") };

export function getTranslator(locale: Locale): Translator {
  return TRANSLATORS[locale];
}

interface LocaleStore {
  locale: Locale;
  /** True once the saved / browser locale has been applied on the client. */
  hydrated: boolean;
  setLocale: (locale: Locale) => void;
  hydrate: () => void;
}

/**
 * Current UI language. It starts as English (what the static export is rendered in) and
 * `LocaleSync` applies the saved / detected one before the first paint on the client.
 */
export const useLocaleStore = create<LocaleStore>()((set, get) => ({
  locale: DEFAULT_LOCALE,
  hydrated: false,
  setLocale: (locale) => {
    writeStorage(LOCALE_STORAGE_KEY, locale);
    set({ locale, hydrated: true });
  },
  hydrate: () => {
    if (get().hydrated) return;
    set({ locale: detectLocale(), hydrated: true });
  },
}));

/** Translator for the current locale, for non-React code (toasts, error mapping…). */
export function t(key: MessageKey, params?: Params): string {
  return TRANSLATORS[useLocaleStore.getState().locale](key, params);
}

export function currentLocale(): Locale {
  return useLocaleStore.getState().locale;
}

export function currentTranslator(): Translator {
  return TRANSLATORS[useLocaleStore.getState().locale];
}

export function useLocale(): [Locale, (l: Locale) => void] {
  const locale = useLocaleStore((s) => s.locale);
  const setLocale = useLocaleStore((s) => s.setLocale);
  return [locale, setLocale];
}

/** Translator bound to the current locale; components re-render when it changes. */
export function useT(): Translator {
  const locale = useLocaleStore((s) => s.locale);
  return useMemo(() => TRANSLATORS[locale], [locale]);
}

// ---------------------------------------------------------------- Intl helpers

const dateFormats = new Map<string, Intl.DateTimeFormat>();

export function formatDate(
  value: string | number | Date,
  options: Intl.DateTimeFormatOptions = { dateStyle: "medium" },
  locale: Locale = currentLocale(),
): string {
  const d = value instanceof Date ? value : new Date(value);
  if (Number.isNaN(d.getTime())) return "";
  const k = `${locale}|${JSON.stringify(options)}`;
  let f = dateFormats.get(k);
  if (!f) {
    f = new Intl.DateTimeFormat(locale, options);
    dateFormats.set(k, f);
  }
  return f.format(d);
}

const relFormats = new Map<Locale, Intl.RelativeTimeFormat>();

export function formatRelativeTime(
  iso: string,
  now: number = Date.now(),
  locale: Locale = currentLocale(),
): string {
  const ts = Date.parse(iso);
  if (!Number.isFinite(ts)) return "";
  let rtf = relFormats.get(locale);
  if (!rtf) {
    rtf = new Intl.RelativeTimeFormat(locale, { numeric: "auto" });
    relFormats.set(locale, rtf);
  }
  const diff = Math.round((ts - now) / 1000);
  const abs = Math.abs(diff);
  if (abs < 60) return rtf.format(diff, "second");
  if (abs < 3600) return rtf.format(Math.round(diff / 60), "minute");
  if (abs < 86400) return rtf.format(Math.round(diff / 3600), "hour");
  if (abs < 86400 * 30) return rtf.format(Math.round(diff / 86400), "day");
  return formatDate(ts, { dateStyle: "medium" }, locale);
}

export function formatNumber(n: number, options?: Intl.NumberFormatOptions, locale: Locale = currentLocale()): string {
  return new Intl.NumberFormat(locale, options).format(n);
}
