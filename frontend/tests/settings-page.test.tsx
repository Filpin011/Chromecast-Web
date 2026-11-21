import { fireEvent, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import SettingsPage from "@/app/settings/page";
import { settingsErrorMessage } from "@/hooks/queries";
import { api, ApiError } from "@/lib/api";
import type { Settings } from "@/lib/api/types";
import { isHttpUrl } from "@/lib/url";
import { renderWithProviders } from "./render";

const SETTINGS: Settings = {
  idle_image_url: null,
  show_idle_on_connect: true,
  show_idle_on_stop: true,
  default_device_id: null,
  public_base_url: null,
  force_proxy: false,
  adblock_enabled: true,
  adblock_disabled_hosts: [],
  popup_policy: "ask",
  popup_blocked_hosts: [],
};

beforeEach(() => {
  vi.spyOn(api.settings, "get").mockResolvedValue(SETTINGS);
  vi.spyOn(api.system, "health").mockResolvedValue({ ok: true } as never);
  vi.spyOn(api.filters, "list").mockResolvedValue({ lists: [] } as never);
});

afterEach(() => vi.restoreAllMocks());

describe("isHttpUrl", () => {
  it("accepts only absolute http(s) URLs with a host", () => {
    expect(isHttpUrl("http://192.168.1.10:8000")).toBe(true);
    expect(isHttpUrl(" https://img.example.com/a.jpg ")).toBe(true);
    for (const bad of ["", "example.com/a.jpg", "ftp://x.example", "http://", "https://a b.example", "javascript:alert(1)"]) {
      expect(isHttpUrl(bad), bad).toBe(false);
    }
  });
});

describe("settingsErrorMessage", () => {
  it("explains a rejected URL instead of the generic 'Invalid request'", () => {
    const e = new ApiError(422, "idle_image_url: must be an http(s) URL", "validation_error");
    expect(settingsErrorMessage(e, { idle_image_url: "nope" })).toBe("Not saved: enter a full http(s) address");
    expect(settingsErrorMessage(e, { public_base_url: "nope" })).toBe("Not saved: enter a full http(s) address");
    expect(settingsErrorMessage(e, { force_proxy: true })).not.toContain("http(s)");
  });
});

describe("Settings page", () => {
  it("does not send an invalid URL, keeps it in the field and says why", async () => {
    const update = vi.spyOn(api.settings, "update").mockResolvedValue(SETTINGS);
    renderWithProviders(<SettingsPage />);
    const input = await screen.findByLabelText("Image URL");
    await userEvent.type(input, "example.com/idle.jpg{Enter}");
    expect(update).not.toHaveBeenCalled();
    expect(input).toHaveValue("example.com/idle.jpg");
    expect(input).toHaveAttribute("aria-invalid", "true");
    expect(screen.getByRole("alert")).toHaveTextContent("Enter a full address starting with http:// or https://");
    expect(input).toHaveAccessibleDescription(/Enter a full address/);
    // typing again clears the error
    await userEvent.type(input, "x");
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("saves a valid URL and confirms briefly with 'Saved'", async () => {
    const update = vi
      .spyOn(api.settings, "update")
      .mockImplementation(async (patch) => ({ ...SETTINGS, ...patch }) as Settings);
    renderWithProviders(<SettingsPage />);
    const input = await screen.findByLabelText("Server public URL");
    fireEvent.change(input, { target: { value: "http://192.168.1.10:8000" } });
    fireEvent.keyDown(input, { key: "Enter" });
    await waitFor(() => expect(update).toHaveBeenCalledWith({ public_base_url: "http://192.168.1.10:8000" }));
    expect(await screen.findByRole("status")).toHaveTextContent("Saved");
  });

  it("confirms a toggle with the same 'Saved' status", async () => {
    vi.spyOn(api.settings, "update").mockImplementation(async (patch) => ({ ...SETTINGS, ...patch }) as Settings);
    renderWithProviders(<SettingsPage />);
    await userEvent.click(await screen.findByRole("switch", { name: "Force proxy" }));
    await waitFor(() => expect(screen.getByRole("status")).toHaveTextContent("Saved"));
  });

  it("gives the filter-list refresh its own label", async () => {
    renderWithProviders(<SettingsPage />);
    expect(await screen.findByRole("button", { name: "Refresh" })).toBeInTheDocument();
  });
});
