"use client";

import { Dialog, DialogContent, DialogTitle } from "@/components/ui/dialog";
import { Drawer, DrawerContent, DrawerTitle } from "@/components/ui/drawer";
import { useIsDesktop } from "@/hooks/use-media-query";
import { useT } from "@/i18n";
import { useLocalPlayerStore } from "@/stores/local-player-store";
import { DEVICE_SHEET_TITLE, useUiStore } from "@/stores/ui-store";
import { DevicePickerContent } from "./device-picker";

/**
 * App-wide device sheet (bottom drawer on phones, dialog on desktop).
 *
 * While the "Watch here" player is open, the `nested` instance mounted inside it takes over: a dialog
 * stacked on top of the player. A sibling modal would treat taps in it as outside presses of the player,
 * and a nested drawer would fade the player's content out.
 */
export function DevicePickerSheet({ nested = false }: { nested?: boolean }) {
  const localOpen = useLocalPlayerStore((s) => s.media !== null);
  const open = useUiStore((s) => s.devicePickerOpen) && localOpen === nested;
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
  // the visible heading is the dialog's title itself: one accessible name (see `titleAs`)
  const content = (Title: typeof DialogTitle | typeof DrawerTitle) => (
    <DevicePickerContent title={title} titleAs={Title} onPicked={onPicked} onCancel={() => setOpen(false)} connectOnPick={!forCast} />
  );

  if (isDesktop || nested) {
    return (
      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent className="gap-0 overflow-hidden p-0 sm:max-w-md" showCloseButton={false}>
          {content(DialogTitle)}
        </DialogContent>
      </Dialog>
    );
  }
  return (
    <Drawer open={open} onOpenChange={setOpen} showSwipeHandle>
      <DrawerContent>
        {content(DrawerTitle)}
      </DrawerContent>
    </Drawer>
  );
}
