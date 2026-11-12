import { fireEvent, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("sonner", () => {
  const toast = Object.assign(vi.fn(), { error: vi.fn(), success: vi.fn(), loading: vi.fn() });
  return { toast };
});

import { DevicePickerContent } from "@/components/devices/device-picker";
import { DevicePickerSheet } from "@/components/devices/device-picker-sheet";
import { api } from "@/lib/api";
import { useAppStore } from "@/stores/app-store";
import { openDevicePicker, useUiStore } from "@/stores/ui-store";
import { makeAppState, makeDevice, makePlayer } from "./fixtures";
import { renderWithProviders } from "./render";

const camera = makeDevice({ id: "dev-2", name: "Camera", host: "192.168.1.51" });
const offline = makeDevice({ id: "dev-3", name: "Cucina", online: false });

beforeEach(() => {
  useAppStore.getState().reset();
  useAppStore.getState().applySnapshot(
    makeAppState({ devices: [makeDevice(), camera, offline], active_device_id: null, players: {} }),
  );
});

function renderPicker() {
  const onPicked = vi.fn();
  const onCancel = vi.fn();
  renderWithProviders(<DevicePickerContent title="Invia video a…" onPicked={onPicked} onCancel={onCancel} />);
  return { onPicked, onCancel };
}

describe("DevicePickerContent", () => {
  it("lists online devices first and disables offline ones", () => {
    renderPicker();
    expect(screen.getByText("Invia video a…")).toBeInTheDocument();
    const items = screen.getAllByRole("listitem").map((li) => li.textContent);
    expect(items[0]).toContain("Camera");
    expect(items[1]).toContain("Salotto");
    expect(items[2]).toContain("Cucina");
    expect(screen.getByText("Offline")).toBeInTheDocument();
    expect(screen.getByText("Cucina").closest("button")).toBeDisabled();
  });

  it("connects to a device, makes it active and reports it", async () => {
    const connect = vi.spyOn(api.devices, "connect").mockResolvedValue(makePlayer({ device_id: "dev-2" }));
    const { onPicked } = renderPicker();
    fireEvent.click(screen.getByText("Camera"));
    await waitFor(() => expect(onPicked).toHaveBeenCalledWith("dev-2"));
    expect(connect).toHaveBeenCalledWith("dev-2");
    expect(useAppStore.getState().appState?.active_device_id).toBe("dev-2");
    expect(useAppStore.getState().appState?.players["dev-2"].connected).toBe(true);
  });

  it("does not reconnect the already active device", async () => {
    useAppStore.getState().applySnapshot(makeAppState({ version: 2 }));
    const connect = vi.spyOn(api.devices, "connect");
    const { onPicked } = renderPicker();
    expect(screen.getByLabelText("Connesso")).toBeInTheDocument();
    fireEvent.click(screen.getByText("Salotto"));
    expect(onPicked).toHaveBeenCalledWith("dev-1");
    expect(connect).not.toHaveBeenCalled();
  });

  it("refreshes the list with discovery", async () => {
    const discover = vi.spyOn(api.devices, "discover").mockResolvedValue([]);
    renderPicker();
    fireEvent.click(screen.getByText("Aggiorna elenco"));
    expect(await screen.findByText("Ricerca in corso…")).toBeInTheDocument();
    await waitFor(() => expect(discover).toHaveBeenCalled());
    await waitFor(() => expect(screen.getByText("Aggiorna elenco")).toBeInTheDocument());
  });

  it("adds a device by IP", async () => {
    const add = vi.spyOn(api.devices, "addManual").mockResolvedValue(makeDevice({ id: "manual-x", manual: true }));
    renderPicker();
    fireEvent.click(screen.getByText("Aggiungi per indirizzo IP"));
    const input = await screen.findByLabelText("Indirizzo IP");
    const submit = screen.getByRole("button", { name: "Aggiungi" });
    expect(submit).toBeDisabled();
    fireEvent.change(input, { target: { value: "192.168.1.77:8009" } });
    fireEvent.click(submit);
    await waitFor(() => expect(add).toHaveBeenCalledWith({ host: "192.168.1.77", port: 8009 }));
  });

  it("cancels", () => {
    const { onCancel } = renderPicker();
    fireEvent.click(screen.getByText("Annulla"));
    expect(onCancel).toHaveBeenCalled();
  });
});

describe("requestDevice flow", () => {
  it("resolves with the picked device and null on dismiss", async () => {
    const p = useUiStore.getState().requestDevice();
    expect(useUiStore.getState().devicePickerOpen).toBe(true);
    useUiStore.getState().resolveDevice("dev-9");
    await expect(p).resolves.toBe("dev-9");

    const p2 = useUiStore.getState().requestDevice();
    useUiStore.getState().setDevicePickerOpen(false);
    await expect(p2).resolves.toBeNull();
  });
});

describe("DevicePickerSheet", () => {
  it("when opened by a cast, only picks the target: the cast connects (no idle-image flash)", async () => {
    useUiStore.setState({ devicePickerOpen: false, pendingDevice: null });
    const connect = vi.spyOn(api.devices, "connect");
    renderWithProviders(<DevicePickerSheet />);
    const picked = useUiStore.getState().requestDevice();
    fireEvent.click(await screen.findByText("Camera"));
    await expect(picked).resolves.toBe("dev-2");
    expect(connect).not.toHaveBeenCalled();
    expect(useAppStore.getState().appState?.active_device_id).toBe("dev-2");
  });

  it("when opened from the header, picking connects as before", async () => {
    useUiStore.setState({ devicePickerOpen: false, pendingDevice: null });
    const connect = vi.spyOn(api.devices, "connect").mockResolvedValue(makePlayer({ device_id: "dev-2" }));
    renderWithProviders(<DevicePickerSheet />);
    openDevicePicker();
    fireEvent.click(await screen.findByText("Camera"));
    await waitFor(() => expect(connect).toHaveBeenCalledWith("dev-2"));
  });

  it("uses the same 'Invia video a…' title when opened from a header cast icon", async () => {
    useUiStore.setState({ devicePickerOpen: false, pendingDevice: null });
    renderWithProviders(<DevicePickerSheet />);
    openDevicePicker();
    expect(await screen.findAllByText("Invia video a…")).not.toHaveLength(0);
    expect(screen.queryByText("Dispositivi")).not.toBeInTheDocument();
  });
});
