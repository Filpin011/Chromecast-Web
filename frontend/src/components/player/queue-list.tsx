"use client";

import { ArrowDown, ArrowUp, GripVertical, ListMusic, Trash2 } from "lucide-react";
import { Reorder, useDragControls } from "motion/react";
import { useEffect, useRef, useState } from "react";
import { toast } from "sonner";
import { RowMenu, type RowAction } from "@/components/common/list-row";
import { Thumb } from "@/components/common/thumb";
import { api } from "@/lib/api";
import type { QueueItem } from "@/lib/api/types";
import { useT } from "@/i18n";
import { haptic } from "@/lib/haptics";
import { errorMessage } from "@/lib/query";
import { useAppStore } from "@/stores/app-store";

const HINT_ID = "queue-drag-hint";

function QueueRow({
  item,
  index,
  count,
  onRemove,
  onMove,
  onDragEnd,
}: {
  item: QueueItem;
  index: number;
  count: number;
  onRemove: () => void;
  /** Move by `delta` places (-1 = up); `fromKeyboard` keeps the focus on the handle. */
  onMove: (delta: number, fromKeyboard: boolean) => void;
  onDragEnd: () => void;
}) {
  const t = useT();
  const controls = useDragControls();
  const actions: RowAction[] = [];
  if (index > 0) actions.push({ label: t("queue.moveUp"), icon: ArrowUp, onClick: () => onMove(-1, false) });
  if (index < count - 1) actions.push({ label: t("queue.moveDown"), icon: ArrowDown, onClick: () => onMove(1, false) });
  actions.push({ label: t("queue.remove"), icon: Trash2, onClick: onRemove, destructive: true, separated: actions.length > 0 });
  return (
    <Reorder.Item
      value={item}
      dragListener={false}
      dragControls={controls}
      onDragEnd={onDragEnd}
      className="flex items-center gap-2 rounded-xl bg-card p-1.5 pr-1 ring-1 ring-border"
      layout="position"
    >
      {/* drag with a pointer, or focus it and use ↑ / ↓ (the ⋮ menu offers the same moves) */}
      <button
        type="button"
        data-queue-handle={item.id}
        aria-label={t("queue.drag", { name: item.title })}
        aria-describedby={HINT_ID}
        onPointerDown={(e) => {
          haptic(4);
          controls.start(e);
        }}
        onKeyDown={(e) => {
          if (e.key !== "ArrowUp" && e.key !== "ArrowDown") return;
          e.preventDefault();
          onMove(e.key === "ArrowUp" ? -1 : 1, true);
        }}
        className="grid size-11 shrink-0 cursor-grab touch-none place-items-center rounded-lg text-muted-foreground active:cursor-grabbing"
      >
        <GripVertical className="size-4" />
      </button>
      <Thumb src={item.thumbnail} className="size-10" />
      <div className="min-w-0 flex-1">
        <p className="truncate text-sm font-medium">{item.title}</p>
        <p className="text-xs text-muted-foreground">#{index + 1}</p>
      </div>
      <RowMenu label={t("playlists.actionsFor", { name: item.title })} actions={actions} />
    </Reorder.Item>
  );
}

/**
 * Apply a local drag order on top of the latest server queue. Snapshots keep arriving mid-drag
 * (another phone adds/removes, the queue advances on FINISHED): ids no longer in the queue are
 * dropped and new ones are appended. Kept rows keep their object identity: Reorder tracks the
 * dragged row by reference, and a queue item's content never changes for a given id.
 */
export function reconcileOrder(order: readonly QueueItem[] | null, queue: readonly QueueItem[]): QueueItem[] {
  if (!order) return [...queue];
  const live = new Set(queue.map((i) => i.id));
  const kept = order.filter((i) => live.has(i.id));
  const seen = new Set(kept.map((i) => i.id));
  return [...kept, ...queue.filter((i) => !seen.has(i.id))];
}

/** `items` with the one at `from` moved to `to` (clamped); the same array when nothing moves. */
export function moveItem<T>(items: readonly T[], from: number, to: number): readonly T[] {
  const target = Math.max(0, Math.min(items.length - 1, to));
  if (from === target || from < 0 || from >= items.length) return items;
  const next = [...items];
  const [moved] = next.splice(from, 1);
  next.splice(target, 0, moved);
  return next;
}

/** Server-side play queue: reorder by drag, arrow keys on a handle or the row menu; remove. */
export function QueueList({ deviceId, queue }: { deviceId: string; queue: QueueItem[] }) {
  const t = useT();
  const [order, setOrder] = useState<QueueItem[] | null>(null);
  const [announcement, setAnnouncement] = useState("");
  const refocus = useRef<string | null>(null);
  const items = reconcileOrder(order, queue);

  // a moved row's DOM node is re-inserted, which drops the focus: give it back to its handle
  useEffect(() => {
    const id = refocus.current;
    if (!id) return;
    refocus.current = null;
    document.querySelector<HTMLElement>(`[data-queue-handle="${CSS.escape(id)}"]`)?.focus();
  });

  const sendOrder = async (ids: string[]) => {
    try {
      const p = await api.player.reorderQueue(deviceId, ids);
      useAppStore.getState().applyPlayer(p);
    } catch (e) {
      toast.error(errorMessage(e, t("queue.reorderFailed")));
    } finally {
      setOrder(null);
    }
  };

  const commitOrder = async () => {
    if (!order) return;
    const ids = items.map((i) => i.id);
    if (ids.join() === queue.map((i) => i.id).join()) {
      setOrder(null);
      return;
    }
    await sendOrder(ids);
  };

  const move = (index: number, delta: number, fromKeyboard: boolean) => {
    const next = moveItem(items, index, index + delta);
    if (next === items) return;
    haptic(4);
    const item = items[index];
    if (fromKeyboard) refocus.current = item.id;
    setOrder([...next]);
    setAnnouncement(t("queue.movedTo", { name: item.title, position: next.indexOf(item) + 1 }));
    void sendOrder(next.map((i) => i.id));
  };

  const remove = async (id: string) => {
    haptic();
    try {
      const p = await api.player.removeFromQueue(deviceId, id);
      useAppStore.getState().applyPlayer(p);
    } catch (e) {
      toast.error(errorMessage(e, t("queue.removeFailed")));
    }
  };

  if (!items.length) {
    return (
      <div className="flex flex-col items-center gap-2 py-8 text-center text-sm text-muted-foreground">
        <ListMusic className="size-6" />
        {t("queue.empty")}
      </div>
    );
  }

  return (
    <>
      <Reorder.Group axis="y" values={items} onReorder={setOrder} className="space-y-2" aria-label={t("common.queue")}>
        {items.map((item, i) => (
          <QueueRow
            key={item.id}
            item={item}
            index={i}
            count={items.length}
            onRemove={() => remove(item.id)}
            onMove={(delta, kb) => move(i, delta, kb)}
            onDragEnd={commitOrder}
          />
        ))}
      </Reorder.Group>
      <p id={HINT_ID} hidden>
        {t("queue.dragHint")}
      </p>
      <p role="status" className="sr-only">
        {announcement}
      </p>
    </>
  );
}
