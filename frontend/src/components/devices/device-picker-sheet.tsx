"use client";

import { Dialog, DialogContent, DialogTitle } from "@/components/ui/dialog";
import { Drawer, DrawerContent, DrawerTitle } from "@/components/ui/drawer";
import { useIsDesktop } from "@/hooks/use-media-query";
import { useT } from "@/i18n";
import { DEVICE_SHEET_TITLE, useUiStore } from "@/stores/ui-store";
import { DevicePickerContent } from "./device-picker";

/** App-wide device sheet (bottom drawer on phones, dialog on desktop). */
export function DevicePickerSheet() {
  const open = useUiStore((s) => s.devicePickerOpen);
  const setOpen = useUiStore((s) => s.setDevicePickerOpen);
  // opened by a cast (requestDevice): just choose the target, the cast itself connects
  const forCast = useUiStore((s) => s.pendingDevice !== null);
  const isDesktop = useIsDesktop();
  const t = useT();
  const title = t(DEVICE_SHEET_TITLE);

  const onPicked = (id: string) => {
    useUiStore.getState().resolveDevice(id);
    setOpen(false);
  };
  const content = <DevicePickerContent title={title} onPicked={onPicked} onCancel={() => setOpen(false)} connectOnPick={!forCast} />;

  if (isDesktop) {
    return (
      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent className="gap-0 overflow-hidden p-0 sm:max-w-md" showCloseButton={false}>
          <DialogTitle className="sr-only">{title}</DialogTitle>
          {content}
        </DialogContent>
      </Dialog>
    );
  }
  return (
    <Drawer open={open} onOpenChange={setOpen} showSwipeHandle>
      <DrawerContent>
        <DrawerTitle className="sr-only">{title}</DrawerTitle>
        {content}
      </DrawerContent>
    </Drawer>
  );
}
