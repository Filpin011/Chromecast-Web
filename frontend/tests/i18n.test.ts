import { afterAll, afterEach, beforeAll, describe, expect, it } from "vitest";
import {
  detectLocale,
  formatRelativeTime,
  getTranslator,
  interpolate,
  LOCALE_STORAGE_KEY,
  LOCALES,
  t,
  useLocaleStore,
} from "@/i18n";
import { en } from "@/i18n/en";
import { it as itDict } from "@/i18n/it";
import { ApiError } from "@/lib/api";
import { ERROR_CODES, ERROR_REASONS, errorMessage, translateErrorCode } from "@/lib/query";

const DICTS = { en, it: itDict } as Record<string, Record<string, string>>;
const placeholders = (s: string) => [...s.matchAll(/\{(\w+)\}/g)].map((m) => m[1]).sort();

// jsdom on recent Node exposes a non-functional localStorage: use an in-memory one here.
const realStorage = Object.getOwnPropertyDescriptor(window, "localStorage");
beforeAll(() => {
  const data = new Map<string, string>();
  const memory = {
    getItem: (k: string) => data.get(k) ?? null,
    setItem: (k: string, v: string) => void data.set(k, String(v)),
    removeItem: (k: string) => void data.delete(k),
    clear: () => data.clear(),
  };
  Object.defineProperty(window, "localStorage", { value: memory, configurable: true });
});
afterAll(() => {
  if (realStorage) Object.defineProperty(window, "localStorage", realStorage);
});

afterEach(() => {
  useLocaleStore.setState({ locale: "en", hydrated: false });
  window.localStorage.clear();
});

describe("dictionaries", () => {
  it("have identical key sets", () => {
    expect(Object.keys(itDict).sort()).toEqual(Object.keys(en).sort());
  });

  it("have no empty values", () => {
    for (const locale of LOCALES) {
      const empty = Object.entries(DICTS[locale]).filter(([, v]) => typeof v !== "string" || !v.trim());
      expect(empty, locale).toEqual([]);
    }
  });

  it("use the same placeholders in every language", () => {
    const mismatched = Object.keys(en).filter(
      (k) => placeholders(en[k as keyof typeof en]).join() !== placeholders(itDict[k as keyof typeof en]).join(),
    );
    expect(mismatched).toEqual([]);
  });

  it("define every plural with an `_other` form", () => {
    for (const k of Object.keys(en).filter((k) => /_(zero|one|few|many)$/.test(k))) {
      expect(en, k).toHaveProperty(k.replace(/_(zero|one|few|many)$/, "_other"));
    }
  });

  it("label the cast action with one verb everywhere", () => {
    for (const locale of LOCALES) expect(DICTS[locale]["common.cast"], locale).toBe(DICTS[locale]["media.castShort"]);
  });

  it("translate every API error code and reason", () => {
    for (const code of ERROR_CODES) expect(en, code).toHaveProperty(`errors.${code}`);
    for (const reason of ERROR_REASONS) expect(en, reason).toHaveProperty(`errors.reason.${reason}`);
  });
});

describe("translator", () => {
  it("interpolates and leaves unknown placeholders alone", () => {
    expect(interpolate("Hi {name}, {x}", { name: "Ann" })).toBe("Hi Ann, {x}");
    expect(getTranslator("en")("devices.added", { name: "TV" })).toBe("TV added");
    expect(getTranslator("it")("devices.added", { name: "TV" })).toBe("TV aggiunto");
  });

  it("picks plural forms with Intl.PluralRules and formats the count", () => {
    const en = getTranslator("en");
    const it = getTranslator("it");
    expect(en.plural("playlists.channels", 1)).toBe("1 channel");
    expect(en.plural("playlists.channels", 1200)).toBe("1,200 channels");
    expect(it.plural("playlists.channels", 1)).toBe("1 canale");
    expect(it.plural("playlists.channels", 1200)).toBe("1200 canali");
    expect(it.plural("playlists.channels", 12000)).toBe("12.000 canali");
  });

  it("maybe() returns undefined for unknown keys", () => {
    expect(getTranslator("en").maybe("errors.nope")).toBeUndefined();
    expect(getTranslator("it").maybe("errors.queue_empty")).toBe("La coda è vuota");
  });

  it("the global t follows the current locale", () => {
    expect(t("common.cancel")).toBe("Cancel");
    useLocaleStore.getState().setLocale("it");
    expect(t("common.cancel")).toBe("Annulla");
    expect(window.localStorage.getItem(LOCALE_STORAGE_KEY)).toBe("it");
  });
});

describe("detectLocale", () => {
  it("prefers the saved choice, then an Italian browser, else English", () => {
    expect(detectLocale("en", ["it-IT"])).toBe("en");
    expect(detectLocale("it", ["en-US"])).toBe("it");
    expect(detectLocale(null, ["it-IT", "en"])).toBe("it");
    expect(detectLocale(null, ["it"])).toBe("it");
    expect(detectLocale(null, ["en-GB", "it"])).toBe("en");
    expect(detectLocale("fr", ["de-DE"])).toBe("en");
    expect(detectLocale(null, [])).toBe("en");
  });

  it("hydrate() applies the saved locale once", () => {
    window.localStorage.setItem(LOCALE_STORAGE_KEY, "it");
    useLocaleStore.getState().hydrate();
    expect(useLocaleStore.getState().locale).toBe("it");
  });
});

describe("Intl formatting", () => {
  const now = Date.parse("2026-01-10T12:00:00Z");
  it("formats relative times per locale", () => {
    expect(formatRelativeTime("2026-01-10T11:57:00Z", now, "en")).toBe("3 minutes ago");
    expect(formatRelativeTime("2026-01-10T11:57:00Z", now, "it")).toBe("3 minuti fa");
    expect(formatRelativeTime("2026-01-09T12:00:00Z", now, "it")).toBe("ieri");
    expect(formatRelativeTime("nope", now, "en")).toBe("");
  });
});

describe("API errors by code", () => {
  it("translates code, prefers a known reason (with params), falls back to detail", () => {
    const en = getTranslator("en");
    const it = getTranslator("it");
    expect(translateErrorCode("queue_empty", undefined, undefined, it)).toBe("La coda è vuota");
    expect(translateErrorCode("resolve_failed", "connect_failed", { host: "tv.example" }, en)).toBe(
      "Couldn’t connect to tv.example",
    );
    expect(translateErrorCode("resolve_failed", "brand_new_reason", undefined, en)).toBe(en("errors.resolve_failed"));
    expect(translateErrorCode("weird", undefined, undefined, en)).toBeUndefined();
    expect(errorMessage(new ApiError(500, "boom", "weird"))).toBe("boom");
    expect(errorMessage(new ApiError(502, "x", "resolve_failed", "upstream_http", { status: 403 }))).toBe(
      "The server answered with error 403",
    );
    useLocaleStore.getState().setLocale("it");
    expect(errorMessage(new ApiError(502, "x", "resolve_failed", "upstream_http", { status: 403 }))).toBe(
      "Il server ha risposto con l’errore 403",
    );
  });
});
