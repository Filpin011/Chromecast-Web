"use client";

import { GripVertical, ListMusic, X } from "lucide-react";
import { Reorder, useDragControls } from "motion/react";
import { useState } from "react";
import { toast } from "sonner";
import { Thumb } from "@/components/common/thumb";
import { Button } from "@/components/ui/button";
import { api } from "@/lib/api";
import type { QueueItem } from "@/lib/api/types";
import { haptic } from "@/lib/haptics";
import { errorMessage } from "@/lib/query";
import { useAppStore } from "@/stores/app-store";

function QueueRow({
  item,
  index,
  onRemove,
  onDragEnd,
}: {
  item: QueueItem;
  index: number;
  onRemove: () => void;
  onDragEnd: () => void;
}) {
  const controls = useDragControls();
  return (
    <Reorder.Item
      value={item}
      dragListener={false}
      dragControls={controls}
      onDragEnd={onDragEnd}
      className="flex items-center gap-2 rounded-xl bg-card p-1.5 pr-1 ring-1 ring-border"
      layout="position"
    >
      <button
        type="button"
        aria-label={`Trascina ${item.title}`}
        onPointerDown={(e) => {
          haptic(4);
          controls.start(e);
        }}
        className="grid size-11 shrink-0 cursor-grab touch-none place-items-center text-muted-foreground active:cursor-grabbing"
      >
        <GripVertical className="size-4" />
      </button>
      <Thumb src={item.thumbnail} className="size-10" />
      <div className="min-w-0 flex-1">
        <p className="truncate text-sm font-medium">{item.title}</p>
        <p className="text-xs text-muted-foreground">#{index + 1}</p>
      </div>
      <Button variant="ghost" size="icon" aria-label={`Rimuovi ${item.title}`} onClick={onRemove}>
        <X className="size-4" />
      </Button>
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

/** Server-side play queue with drag-to-reorder and remove. */
export function QueueList({ deviceId, queue }: { deviceId: string; queue: QueueItem[] }) {
  const [order, setOrder] = useState<QueueItem[] | null>(null);
  const items = reconcileOrder(order, queue);

  const commitOrder = async () => {
    if (!order) return;
    const ids = items.map((i) => i.id);
    if (ids.join() === queue.map((i) => i.id).join()) {
      setOrder(null);
      return;
    }
    try {
      const p = await api.player.reorderQueue(deviceId, ids);
      useAppStore.getState().applyPlayer(p);
    } catch (e) {
      toast.error(errorMessage(e, "Riordino non riuscito"));
    } finally {
      setOrder(null);
    }
  };

  const remove = async (id: string) => {
    haptic();
    try {
      const p = await api.player.removeFromQueue(deviceId, id);
      useAppStore.getState().applyPlayer(p);
    } catch (e) {
      toast.error(errorMessage(e, "Rimozione non riuscita"));
    }
  };

  if (!items.length) {
    return (
      <div className="flex flex-col items-center gap-2 py-8 text-center text-sm text-muted-foreground">
        <ListMusic className="size-6" />
        La coda è vuota. Usa “Aggiungi alla coda” da qualsiasi contenuto.
      </div>
    );
  }

  return (
    <Reorder.Group axis="y" values={items} onReorder={setOrder} className="space-y-2" aria-label="Coda">
      {items.map((item, i) => (
        <QueueRow key={item.id} item={item} index={i} onRemove={() => remove(item.id)} onDragEnd={commitOrder} />
      ))}
    </Reorder.Group>
  );
}
