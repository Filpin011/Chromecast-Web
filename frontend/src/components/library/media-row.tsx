"use client";

import { ListPlus, Pencil, Star, Trash2 } from "lucide-react";
import type { ReactNode } from "react";
import { ListRow, type RowAction } from "@/components/common/list-row";
import { Thumb } from "@/components/common/thumb";
import { useT } from "@/i18n";

export interface MediaRowProps {
  title: string;
  subtitle?: ReactNode;
  thumbnail: string | null;
  onCast: () => void;
  onQueue?: () => void;
  onFavorite?: () => void;
  onRename?: () => void;
  onDelete?: () => void;
  disabled?: boolean;
}

/** A castable item as a `ListRow` (tap = cast) with queue / favorite / rename / delete in its menu. */
export function MediaRow({ title, subtitle, thumbnail, onCast, onQueue, onFavorite, onRename, onDelete, disabled }: MediaRowProps) {
  const t = useT();
  const actions: RowAction[] = [];
  if (onQueue) actions.push({ label: t("media.addToQueue"), icon: ListPlus, onClick: onQueue });
  if (onFavorite) actions.push({ label: t("media.addToFavorites"), icon: Star, onClick: onFavorite });
  if (onRename) actions.push({ label: t("favorites.rename"), icon: Pencil, onClick: onRename });
  if (onDelete) actions.push({ label: t("common.delete"), icon: Trash2, onClick: onDelete, destructive: true });
  return (
    <ListRow
      leading={<Thumb src={thumbnail} alt="" className="aspect-video h-12" />}
      title={title}
      subtitle={subtitle}
      onClick={onCast}
      disabled={disabled}
      label={t("captured.castName", { name: title })}
      menuLabel={actions.length ? t("playlists.actionsFor", { name: title }) : undefined}
      actions={actions}
    />
  );
}
