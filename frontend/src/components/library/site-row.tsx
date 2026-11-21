"use client";

import { Pencil, Trash2 } from "lucide-react";
import { ListRow } from "@/components/common/list-row";
import { SiteIcon } from "@/components/favorites/site-tiles";
import type { Favorite } from "@/lib/api/types";
import { useT } from "@/i18n";
import { hostOf } from "@/lib/format";

/** Saved site as a `ListRow`: tap opens it in the remote browser (never a cast); the menu renames / deletes. */
export function SiteRow({
  site,
  onOpen,
  onRename,
  onDelete,
}: {
  site: Favorite;
  onOpen: () => void;
  onRename: () => void;
  onDelete: () => void;
}) {
  const t = useT();
  return (
    <ListRow
      leading={<SiteIcon src={site.thumbnail} />}
      title={site.title}
      subtitle={hostOf(site.input)}
      onClick={onOpen}
      label={t("sites.open", { name: site.title })}
      menuLabel={t("playlists.actionsFor", { name: site.title })}
      actions={[
        { label: t("favorites.rename"), icon: Pencil, onClick: onRename },
        { label: t("common.delete"), icon: Trash2, onClick: onDelete, destructive: true },
      ]}
    />
  );
}
