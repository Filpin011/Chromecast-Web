"use client";

import { Cast } from "lucide-react";
import { Button } from "@/components/ui/button";
import { useActiveStatus, useConnection } from "@/hooks/use-app-state";
import { cn } from "@/lib/utils";
import { openDevicePicker } from "@/stores/ui-store";

/** Cast icon that opens the device sheet; filled when a device is connected. */
export function DeviceButton({ className, showName = false }: { className?: string; showName?: boolean }) {
  const { device, connected, playing } = useActiveStatus();
  const connection = useConnection();
  return (
    <Button
      variant={showName ? "secondary" : "ghost"}
      size={showName ? "default" : "icon"}
      aria-label={device ? `Dispositivo: ${device.name}` : "Scegli dispositivo"}
      onClick={openDevicePicker}
      className={cn("relative", showName && "w-full justify-start", className)}
    >
      <Cast className={cn("size-5", connected && "text-primary")} strokeWidth={connected ? 2.5 : 2} />
      {showName && (
        <span className="min-w-0 flex-1 truncate text-left">{device?.name ?? "Nessun dispositivo"}</span>
      )}
      {(playing || connection !== "open") && (
        <span
          aria-hidden
          className={cn(
            "absolute top-2 right-2 size-2 rounded-full ring-2 ring-background",
            connection !== "open" ? "bg-amber-500" : "bg-success",
          )}
        />
      )}
    </Button>
  );
}
