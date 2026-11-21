"use client";

import { useState, type FormEvent } from "react";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { useRenameFavorite } from "@/hooks/queries";
import type { Favorite } from "@/lib/api/types";
import { useT } from "@/i18n";

/** Rename a favorite (media or site). Open while `favorite` is set. */
export function RenameFavoriteDialog({ favorite, onClose }: { favorite: Favorite | null; onClose: () => void }) {
  return (
    <Dialog open={!!favorite} onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="sm:max-w-md">
        {/* keyed: the draft starts from the favorite being renamed */}
        {favorite && <RenameForm key={favorite.id} favorite={favorite} onClose={onClose} />}
      </DialogContent>
    </Dialog>
  );
}

function RenameForm({ favorite, onClose }: { favorite: Favorite; onClose: () => void }) {
  const t = useT();
  const rename = useRenameFavorite();
  const [title, setTitle] = useState(favorite.title);
  const value = title.trim();
  const submit = (e: FormEvent) => {
    e.preventDefault();
    if (!value) return;
    if (value === favorite.title) return onClose();
    rename.mutate({ id: favorite.id, title: value }, { onSuccess: onClose });
  };
  return (
    <>
      <DialogHeader>
        <DialogTitle>{t("favorites.renameTitle")}</DialogTitle>
      </DialogHeader>
      <form onSubmit={submit} className="space-y-4">
        <div className="space-y-1.5">
          <Label htmlFor="fav-title">{t("favorites.name")}</Label>
          <Input
            id="fav-title"
            autoFocus
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            onFocus={(e) => e.currentTarget.select()}
            className="h-11"
          />
        </div>
        <div className="flex justify-end gap-2">
          <Button type="button" variant="ghost" onClick={onClose}>
            {t("common.cancel")}
          </Button>
          <Button type="submit" disabled={!value || rename.isPending}>
            {t("common.save")}
          </Button>
        </div>
      </form>
    </>
  );
}
