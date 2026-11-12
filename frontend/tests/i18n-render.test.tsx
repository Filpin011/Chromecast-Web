import { act, fireEvent, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("sonner", () => {
  const toast = Object.assign(vi.fn(), { error: vi.fn(), success: vi.fn(), loading: vi.fn() });
  return { toast };
});

import { toast } from "sonner";
import { handleServerMessage } from "@/components/app/state-socket-bridge";
import { DevicePickerContent } from "@/components/devices/device-picker";
import { NowPlayingContent } from "@/components/player/now-playing";
import { LanguagePicker } from "@/components/settings/language-picker";
import { useLocaleStore, type Locale } from "@/i18n";
import { LocaleSync } from "@/i18n/locale-sync";
import { useAppStore } from "@/stores/app-store";
import { makeAppState, makeDevice, makePlayer } from "./fixtures";
import { renderWithProviders } from "./render";

const setLocale = (locale: Locale) => act(() => useLocaleStore.setState({ locale, hydrated: true }));

beforeEach(() => {
  useAppStore.getState().reset();
  useAppStore.getState().applySnapshot(makeAppState({ active_device_id: null, players: {} }));
});
afterEach(() => {
  useLocaleStore.setState({ locale: "en", hydrated: false });
  document.documentElement.lang = "en";
});

describe("components in both languages", () => {
  it.each([
    ["en", "Refresh list", "Add by IP address", "Cancel"],
    ["it", "Aggiorna elenco", "Aggiungi per indirizzo IP", "Annulla"],
  ] as const)("renders the device picker in %s", (locale, refresh, add, cancel) => {
    setLocale(locale);
    renderWithProviders(<DevicePickerContent title="…" onPicked={vi.fn()} onCancel={vi.fn()} />);
    expect(screen.getByRole("button", { name: refresh })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: add })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: cancel })).toBeInTheDocument();
  });

  it("defaults to English", () => {
    renderWithProviders(<NowPlayingContent device={makeDevice()} player={makePlayer()} receivedAt={Date.now()} />);
    expect(screen.getByText("Playing on")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Pause" })).toBeInTheDocument();
  });

  it("switches language instantly from the picker, without remounting", () => {
    renderWithProviders(
      <>
        <LocaleSync />
        <LanguagePicker />
        <NowPlayingContent device={makeDevice()} player={makePlayer()} receivedAt={Date.now()} />
      </>,
    );
    expect(screen.getByRole("radio", { name: "English" })).toHaveAttribute("aria-checked", "true");
    expect(screen.getByRole("button", { name: /Go live/ })).toBeInTheDocument();

    fireEvent.click(screen.getByRole("radio", { name: "Italiano" }));
    expect(screen.getByRole("radio", { name: "Italiano" })).toHaveAttribute("aria-checked", "true");
    expect(screen.getByText("In riproduzione su")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Vai al live/ })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Pausa" })).toBeInTheDocument();
    expect(screen.getByRole("radiogroup", { name: "Lingua" })).toBeInTheDocument();
    expect(document.documentElement.lang).toBe("it");

    fireEvent.click(screen.getByRole("radio", { name: "English" }));
    expect(screen.getByText("Playing on")).toBeInTheDocument();
    expect(document.documentElement.lang).toBe("en");
  });
});

describe("server toasts are translated by code", () => {
  it("uses the code + params in the current language and falls back to the English message", () => {
    handleServerMessage({ type: "toast", level: "error", message: "Playback failed…", code: "playback_failed", params: { title: "News" } });
    expect(toast.error).toHaveBeenLastCalledWith("Playback failed on the Chromecast: “News”");

    setLocale("it");
    handleServerMessage({ type: "toast", level: "error", message: "Playback failed…", code: "playback_failed", params: { title: "News" } });
    expect(toast.error).toHaveBeenLastCalledWith("Riproduzione non riuscita sul Chromecast: “News”");

    handleServerMessage({
      type: "toast",
      level: "error",
      message: "Skipping “Film”: Upstream returned HTTP 410",
      code: "queue_skipped",
      params: { title: "Film", detail: "Upstream returned HTTP 410", error_code: "resolve_failed", error_reason: "upstream_http", status: 410 },
    });
    expect(toast.error).toHaveBeenLastCalledWith("Salto “Film”: Il server ha risposto con l’errore 410");

    handleServerMessage({ type: "toast", level: "info", message: "Something new", code: "brand_new_code" });
    expect(toast).toHaveBeenLastCalledWith("Something new");
  });
});
