import { act, render, screen } from "@testing-library/react";
import { afterAll, afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";
import { LOCALE_STORAGE_KEY, useLocaleStore, useT } from "@/i18n";
import { LOCALE_BOOTSTRAP_SCRIPT, LOCALE_PENDING_AFTER_LOAD_MS, LOCALE_PENDING_CLASS, LOCALE_PENDING_MAX_MS } from "@/i18n/locale-bootstrap";
import { LocaleSync } from "@/i18n/locale-sync";

const root = () => document.documentElement;

// jsdom on recent Node exposes a non-functional localStorage: use an in-memory one here.
const data = new Map<string, string>();
const memory = {
  getItem: (k: string) => data.get(k) ?? null,
  setItem: (k: string, v: string) => void data.set(k, String(v)),
  removeItem: (k: string) => void data.delete(k),
  clear: () => data.clear(),
};
const realWindowStorage = Object.getOwnPropertyDescriptor(window, "localStorage");
const realGlobalStorage = Object.getOwnPropertyDescriptor(globalThis, "localStorage");
beforeAll(() => {
  Object.defineProperty(window, "localStorage", { value: memory, configurable: true });
  Object.defineProperty(globalThis, "localStorage", { value: memory, configurable: true });
});
afterAll(() => {
  if (realWindowStorage) Object.defineProperty(window, "localStorage", realWindowStorage);
  if (realGlobalStorage) Object.defineProperty(globalThis, "localStorage", realGlobalStorage);
});

function setLanguages(langs: string[]) {
  vi.spyOn(navigator, "languages", "get").mockReturnValue(langs);
  vi.spyOn(navigator, "language", "get").mockReturnValue(langs[0] ?? "");
}

/** Runs the inline <head> script the way the browser does before the first paint. */
function runBootstrap() {
  new Function(LOCALE_BOOTSTRAP_SCRIPT)();
}

function Title() {
  const t = useT();
  return <h1>{t("nav.settings")}</h1>;
}

beforeEach(() => {
  localStorage.clear();
  root().lang = "en";
  root().classList.remove(LOCALE_PENDING_CLASS);
  useLocaleStore.setState({ locale: "en", hydrated: false });
});
afterEach(() => {
  vi.useRealTimers();
  localStorage.clear();
  root().lang = "en";
  root().classList.remove(LOCALE_PENDING_CLASS);
  useLocaleStore.setState({ locale: "en", hydrated: false });
});

describe("locale bootstrap script (runs before first paint)", () => {
  it("sets lang=it and hides the English static HTML for a saved Italian choice", () => {
    setLanguages(["en-US"]);
    localStorage.setItem(LOCALE_STORAGE_KEY, "it");
    runBootstrap();
    expect(root().lang).toBe("it");
    expect(root().classList.contains(LOCALE_PENDING_CLASS)).toBe(true);
  });

  it("detects an Italian browser when nothing is saved", () => {
    setLanguages(["it-IT", "en"]);
    runBootstrap();
    expect(root().lang).toBe("it");
    expect(root().classList.contains(LOCALE_PENDING_CLASS)).toBe(true);
  });

  it("leaves English pages visible (the HTML already is English)", () => {
    setLanguages(["it-IT"]);
    localStorage.setItem(LOCALE_STORAGE_KEY, "en");
    runBootstrap();
    expect(root().lang).toBe("en");
    expect(root().classList.contains(LOCALE_PENDING_CLASS)).toBe(false);
  });

  it("ignores an invalid saved value and falls back to English", () => {
    setLanguages(["de-DE"]);
    localStorage.setItem(LOCALE_STORAGE_KEY, "fr");
    runBootstrap();
    expect(root().lang).toBe("en");
    expect(root().classList.contains(LOCALE_PENDING_CLASS)).toBe(false);
  });

  it("reveals the page by itself shortly after load if the app never hydrates", () => {
    vi.useFakeTimers();
    setLanguages(["it"]);
    runBootstrap();
    vi.advanceTimersByTime(LOCALE_PENDING_AFTER_LOAD_MS * 2);
    // a slow network: scripts still loading, keep waiting instead of flashing English
    expect(root().classList.contains(LOCALE_PENDING_CLASS)).toBe(true);
    window.dispatchEvent(new Event("load"));
    vi.advanceTimersByTime(LOCALE_PENDING_AFTER_LOAD_MS - 1);
    expect(root().classList.contains(LOCALE_PENDING_CLASS)).toBe(true);
    vi.advanceTimersByTime(1);
    expect(root().classList.contains(LOCALE_PENDING_CLASS)).toBe(false);
  });

  it("reveals the page after a hard cap even if load never fires", () => {
    vi.useFakeTimers();
    setLanguages(["it"]);
    runBootstrap();
    vi.advanceTimersByTime(LOCALE_PENDING_MAX_MS);
    expect(root().classList.contains(LOCALE_PENDING_CLASS)).toBe(false);
  });

  it("is revealed by LocaleSync once the Italian UI is rendered", () => {
    setLanguages(["en-US"]);
    localStorage.setItem(LOCALE_STORAGE_KEY, "it");
    runBootstrap();
    render(
      <>
        <LocaleSync />
        <Title />
      </>,
    );
    expect(screen.getByRole("heading")).toHaveTextContent("Impostazioni");
    expect(root().lang).toBe("it");
    expect(root().classList.contains(LOCALE_PENDING_CLASS)).toBe(false);
  });
});

describe("LocaleSync across tabs", () => {
  it("follows a language picked in another tab without writing it back", () => {
    setLanguages(["en-US"]);
    render(
      <>
        <LocaleSync />
        <Title />
      </>,
    );
    expect(screen.getByRole("heading")).toHaveTextContent("Settings");
    const setItem = vi.spyOn(memory, "setItem");

    act(() => {
      window.dispatchEvent(new StorageEvent("storage", { key: LOCALE_STORAGE_KEY, newValue: "it" }));
    });
    expect(screen.getByRole("heading")).toHaveTextContent("Impostazioni");
    expect(root().lang).toBe("it");

    act(() => {
      window.dispatchEvent(new StorageEvent("storage", { key: "other.key", newValue: "en" }));
    });
    expect(screen.getByRole("heading")).toHaveTextContent("Impostazioni");

    act(() => {
      window.dispatchEvent(new StorageEvent("storage", { key: LOCALE_STORAGE_KEY, newValue: "en" }));
    });
    expect(screen.getByRole("heading")).toHaveTextContent("Settings");
    expect(root().lang).toBe("en");
    expect(setItem).not.toHaveBeenCalled();
  });
});
