"use client";

import { Cast, Check, Loader2, Plus, RefreshCw, Speaker, Trash2, Unplug, Users, WifiOff } from "lucide-react";
import { AnimatePresence, motion } from "motion/react";
import { useState, type FormEvent } from "react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { useActiveStatus, useDevices, useDiscovering } from "@/hooks/use-app-state";
import { api } from "@/lib/api";
import type { Device } from "@/lib/api/types";
import { useT } from "@/i18n";
import { haptic } from "@/lib/haptics";
import { errorMessage } from "@/lib/query";
import { cn } from "@/lib/utils";
import { useAppStore } from "@/stores/app-store";

function DeviceIcon({ device, className }: { device: Device; className?: string }) {
  const Icon = device.cast_type === "audio" ? Speaker : device.cast_type === "group" ? Users : Cast;
  return <Icon className={className} />;
}

/** Validate "host" or "host:port" typed in the add-by-IP form. */
export function parseHostInput(raw: string): { host: string; port?: number } | null {
  const v = raw.trim();
  const m = /^([a-zA-Z0-9.-]+|\[[0-9a-fA-F:]+\])(?::(\d{1,5}))?$/.exec(v);
  if (!m) return null;
  const port = m[2] ? Number(m[2]) : undefined;
  if (port !== undefined && (port < 1 || port > 65535)) return null;
  return { host: m[1], port };
}

function AddDeviceForm({ onAdded }: { onAdded: (d: Device) => void }) {
  const t = useT();
  const [value, setValue] = useState("");
  const [busy, setBusy] = useState(false);
  const parsed = parseHostInput(value);
  const submit = async (e: FormEvent) => {
    e.preventDefault();
    if (!parsed) return;
    setBusy(true);
    try {
      const d = await api.devices.addManual(parsed);
      toast.success(t("devices.added", { name: d.name }));
      setValue("");
      onAdded(d);
    } catch (err) {
      toast.error(errorMessage(err, t("devices.unreachable")));
    } finally {
      setBusy(false);
    }
  };
  return (
    <form onSubmit={submit} className="flex gap-2 px-4 pb-2">
      <Input
        aria-label={t("devices.ipAddress")}
        placeholder={t("devices.ipPlaceholder")}
        inputMode="url"
        autoCapitalize="off"
        autoCorrect="off"
        value={value}
        onChange={(e) => setValue(e.target.value)}
        className="h-11"
      />
      <Button type="submit" disabled={!parsed || busy} className="h-11">
        {busy ? <Loader2 className="size-4 animate-spin" /> : t("common.add")}
      </Button>
    </form>
  );
}

export interface DevicePickerContentProps {
  title: string;
  /** Called after the user connected to a device (or picked the already active one). */
  onPicked: (deviceId: string) => void;
  onCancel: () => void;
  /**
   * false when the pick only chooses the target of a cast that follows: the cast auto-connects, and
   * connecting first would flash the idle image before the media. Default true (explicit connect).
   */
  connectOnPick?: boolean;
}

/** "Send video to…" — minimal & fast device list, reused app-wide. */
export function DevicePickerContent({ title, onPicked, onCancel, connectOnPick = true }: DevicePickerContentProps) {
  const t = useT();
  const devices = useDevices();
  const discovering = useDiscovering();
  const { device: active, connected } = useActiveStatus();
  const [connecting, setConnecting] = useState<string | null>(null);
  const [refreshing, setRefreshing] = useState(false);
  const [adding, setAdding] = useState(false);
  const scanning = refreshing || discovering;

  const sorted = [...devices].sort(
    (a, b) => Number(b.online) - Number(a.online) || a.name.localeCompare(b.name),
  );

  const connect = async (d: Device) => {
    haptic(10);
    if ((active?.id === d.id && connected) || !connectOnPick) {
      if (!connectOnPick) useAppStore.getState().setActiveDevice(d.id);
      onPicked(d.id);
      return;
    }
    setConnecting(d.id);
    try {
      const p = await api.devices.connect(d.id);
      const st = useAppStore.getState();
      st.applyPlayer(p);
      st.setActiveDevice(d.id);
      onPicked(d.id);
    } catch (e) {
      toast.error(errorMessage(e, t("devices.connectFailed", { name: d.name })));
    } finally {
      setConnecting(null);
    }
  };

  const disconnect = async (d: Device) => {
    haptic();
    try {
      await api.devices.disconnect(d.id);
    } catch (e) {
      toast.error(errorMessage(e));
    }
  };

  const remove = async (d: Device) => {
    try {
      await api.devices.remove(d.id);
      toast.success(t("devices.removed", { name: d.name }));
    } catch (e) {
      toast.error(errorMessage(e));
    }
  };

  const refresh = async () => {
    haptic();
    setRefreshing(true);
    try {
      await api.devices.discover();
    } catch (e) {
      toast.error(errorMessage(e, t("devices.searchFailed")));
    } finally {
      setRefreshing(false);
    }
  };

  return (
    <div className="flex flex-col pb-[max(env(safe-area-inset-bottom),0.75rem)]">
      <h2 className="px-5 pt-4 pb-2 text-lg font-semibold">{title}</h2>
      <ul className="max-h-[50dvh] overflow-y-auto" aria-label={t("devices.label")} aria-busy={scanning}>
        {sorted.map((d) => {
          const isActive = active?.id === d.id && connected;
          const isConnecting = connecting === d.id;
          return (
            <li key={d.id} className="group flex items-center">
              <button
                type="button"
                disabled={!d.online || !!connecting}
                onClick={() => connect(d)}
                aria-current={isActive ? "true" : undefined}
                className={cn(
                  "flex min-h-14 flex-1 items-center gap-4 px-5 text-left transition-colors active:bg-muted disabled:opacity-50",
                  isActive && "text-primary",
                )}
              >
                <DeviceIcon device={d} className="size-6 shrink-0" />
                <span className="min-w-0 flex-1">
                  <span className="block truncate font-medium">{d.name}</span>
                  <span className="flex items-center gap-1 truncate text-xs text-muted-foreground">
                    {!d.online && <WifiOff className="size-3" />}
                    {d.online ? (d.model ?? d.host) : t("devices.offline")}
                    {d.manual && ` · ${t("devices.manual")}`}
                  </span>
                </span>
                {isConnecting ? (
                  <Loader2 className="size-5 animate-spin" aria-label={t("devices.connecting")} />
                ) : isActive ? (
                  <Check className="size-5" aria-label={t("settings.connected")} />
                ) : null}
              </button>
              {isActive && (
                <Button variant="ghost" size="icon" aria-label={t("devices.disconnectName", { name: d.name })} onClick={() => disconnect(d)} className="mr-2">
                  <Unplug className="size-4" />
                </Button>
              )}
              {d.manual && !isActive && (
                <Button variant="ghost" size="icon" aria-label={t("devices.removeName", { name: d.name })} onClick={() => remove(d)} className="mr-2">
                  <Trash2 className="size-4" />
                </Button>
              )}
            </li>
          );
        })}
        {!sorted.length && !scanning && (
          <li className="px-5 py-6 text-center text-sm text-muted-foreground">
            {t("devices.noneFound")}
          </li>
        )}
      </ul>
      <div className="mt-1 border-t">
        <button
          type="button"
          onClick={refresh}
          disabled={scanning}
          className="flex min-h-13 w-full items-center gap-4 px-5 text-left text-sm font-medium active:bg-muted disabled:opacity-70"
        >
          <RefreshCw className={cn("size-5", scanning && "animate-spin")} />
          {scanning ? t("devices.searching") : t("devices.refresh")}
        </button>
        <button
          type="button"
          onClick={() => setAdding((v) => !v)}
          aria-expanded={adding}
          className="flex min-h-13 w-full items-center gap-4 px-5 text-left text-sm font-medium active:bg-muted"
        >
          <Plus className={cn("size-5 transition-transform", adding && "rotate-45")} />
          {t("devices.addByIp")}
        </button>
        <AnimatePresence initial={false}>
          {adding && (
            <motion.div initial={{ height: 0 }} animate={{ height: "auto" }} exit={{ height: 0 }} className="overflow-hidden">
              <AddDeviceForm onAdded={() => setAdding(false)} />
            </motion.div>
          )}
        </AnimatePresence>
        <button
          type="button"
          onClick={onCancel}
          className="flex min-h-13 w-full items-center justify-center px-5 text-sm font-semibold text-muted-foreground active:bg-muted"
        >
          {t("common.cancel")}
        </button>
      </div>
    </div>
  );
}
