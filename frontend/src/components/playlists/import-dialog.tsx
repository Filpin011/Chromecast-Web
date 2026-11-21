"use client";

import { ClipboardPaste, FileUp, Link2 } from "lucide-react";
import { Spinner } from "@/components/ui/spinner";
import { useRef, useState, type FormEvent } from "react";
import { SegmentedControl } from "@/components/common/segmented-control";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { useImportPlaylist } from "@/hooks/queries";
import type { Playlist, PlaylistImportRequest } from "@/lib/api/types";
import { useT } from "@/i18n";
import { importedPlaylistName } from "@/lib/playlist-import";

type Source = "url" | "file" | "text";

export function ImportPlaylistDialog({
  open,
  onOpenChange,
  onImported,
}: {
  open: boolean;
  onOpenChange: (o: boolean) => void;
  onImported?: (p: Playlist) => void;
}) {
  const t = useT();
  const [tab, setTab] = useState<Source>("url");
  const [url, setUrl] = useState("");
  const [text, setText] = useState("");
  const [name, setName] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);
  const mutation = useImportPlaylist();

  const ready = tab === "url" ? !!url.trim() : tab === "file" ? !!file : !!text.trim();

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    if (!ready) return;
    let req: PlaylistImportRequest;
    if (tab === "url") {
      req = { url: url.trim(), name: name.trim() || undefined };
    } else {
      // the server would call a nameless list just "Playlist": name it after the file, or the date
      const content = tab === "file" && file ? await file.text() : text;
      req = { content, name: importedPlaylistName({ typed: name, content, fileName: tab === "file" ? file?.name : null }) };
    }
    mutation.mutate(req, {
      onSuccess: (p) => {
        onOpenChange(false);
        setUrl("");
        setText("");
        setName("");
        setFile(null);
        onImported?.(p);
      },
    });
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>{t("playlists.import")}</DialogTitle>
          <DialogDescription>{t("import.description")}</DialogDescription>
        </DialogHeader>
        <SegmentedControl
          kind="tab"
          value={tab}
          onChange={setTab}
          compactIcons
          options={[
            { value: "url", label: t("import.fromUrl"), icon: Link2 },
            { value: "file", label: t("import.fromFile"), icon: FileUp },
            { value: "text", label: t("import.fromText"), icon: ClipboardPaste },
          ]}
        />
        <form onSubmit={submit} className="space-y-4">
          {tab === "url" ? (
            <div className="space-y-1.5">
              <Label htmlFor="pl-url">{t("import.url")}</Label>
              <Input
                id="pl-url"
                value={url}
                onChange={(e) => setUrl(e.target.value)}
                placeholder="https://…/playlist.m3u"
                inputMode="url"
                autoCapitalize="off"
                className="h-11"
              />
            </div>
          ) : tab === "file" ? (
            <div className="space-y-1.5">
              <Label>{t("import.file")}</Label>
              <input
                ref={fileRef}
                type="file"
                accept=".m3u,.m3u8,audio/x-mpegurl,application/x-mpegurl,application/vnd.apple.mpegurl,text/plain"
                className="hidden"
                onChange={(e) => setFile(e.target.files?.[0] ?? null)}
              />
              <button
                type="button"
                onClick={() => fileRef.current?.click()}
                className="flex min-h-24 w-full flex-col items-center justify-center gap-1 rounded-xl border-2 border-dashed text-sm text-muted-foreground hover:border-primary/50"
              >
                <FileUp className="size-6" />
                {file ? <span className="font-medium text-foreground">{file.name}</span> : t("import.chooseFile")}
              </button>
            </div>
          ) : (
            <div className="space-y-1.5">
              <Label htmlFor="pl-text">{t("import.text")}</Label>
              <Textarea
                id="pl-text"
                value={text}
                onChange={(e) => setText(e.target.value)}
                placeholder={t("import.textPlaceholder")}
                autoCapitalize="off"
                autoCorrect="off"
                spellCheck={false}
                className="max-h-56 min-h-28 rounded-xl font-mono"
              />
            </div>
          )}
          <div className="space-y-1.5">
            <Label htmlFor="pl-name">{t("import.name")}</Label>
            <Input id="pl-name" value={name} onChange={(e) => setName(e.target.value)} placeholder={t("import.namePlaceholder")} className="h-11" />
          </div>
          <Button type="submit" size="lg" className="w-full" disabled={mutation.isPending || !ready}>
            {mutation.isPending && <Spinner />}
            {t("playlists.importShort")}
          </Button>
        </form>
      </DialogContent>
    </Dialog>
  );
}
