"use client";

import { FileUp, Link2, Loader2 } from "lucide-react";
import { useRef, useState, type FormEvent } from "react";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { useImportPlaylist } from "@/hooks/queries";
import type { Playlist } from "@/lib/api/types";
import { cn } from "@/lib/utils";

export function ImportPlaylistDialog({
  open,
  onOpenChange,
  onImported,
}: {
  open: boolean;
  onOpenChange: (o: boolean) => void;
  onImported?: (p: Playlist) => void;
}) {
  const [tab, setTab] = useState<"url" | "file">("url");
  const [url, setUrl] = useState("");
  const [name, setName] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);
  const mutation = useImportPlaylist();

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    let req;
    if (tab === "url") {
      if (!url.trim()) return;
      req = { url: url.trim(), name: name.trim() || undefined };
    } else {
      if (!file) return;
      const content = await file.text();
      req = { content, name: name.trim() || file.name.replace(/\.m3u8?$/i, "") };
    }
    mutation.mutate(req, {
      onSuccess: (p) => {
        onOpenChange(false);
        setUrl("");
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
          <DialogTitle>Importa playlist</DialogTitle>
          <DialogDescription>M3U / M3U8 da un link IPTV o da un file.</DialogDescription>
        </DialogHeader>
        <div className="grid grid-cols-2 gap-1 rounded-xl bg-muted p-1" role="tablist">
          {(
            [
              ["url", Link2, "Da URL"],
              ["file", FileUp, "Da file"],
            ] as const
          ).map(([t, Icon, label]) => (
            <button
              key={t}
              type="button"
              role="tab"
              aria-selected={tab === t}
              onClick={() => setTab(t)}
              className={cn(
                "flex h-9 items-center justify-center gap-1.5 rounded-lg text-sm font-medium",
                tab === t ? "bg-background shadow-sm" : "text-muted-foreground",
              )}
            >
              <Icon className="size-4" /> {label}
            </button>
          ))}
        </div>
        <form onSubmit={submit} className="space-y-4">
          {tab === "url" ? (
            <div className="space-y-1.5">
              <Label htmlFor="pl-url">URL della playlist</Label>
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
          ) : (
            <div className="space-y-1.5">
              <Label>File M3U</Label>
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
                {file ? <span className="font-medium text-foreground">{file.name}</span> : "Scegli un file .m3u"}
              </button>
            </div>
          )}
          <div className="space-y-1.5">
            <Label htmlFor="pl-name">Nome (opzionale)</Label>
            <Input id="pl-name" value={name} onChange={(e) => setName(e.target.value)} placeholder="Es. IPTV casa" className="h-11" />
          </div>
          <Button
            type="submit"
            size="lg"
            className="w-full"
            disabled={mutation.isPending || (tab === "url" ? !url.trim() : !file)}
          >
            {mutation.isPending && <Loader2 className="size-4 animate-spin" />}
            Importa
          </Button>
        </form>
      </DialogContent>
    </Dialog>
  );
}
