"use client";

import { ListVideo, MoreVertical, Plus, RefreshCw, Trash2 } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { EmptyState } from "@/components/common/empty-state";
import { PageBody, PageHeader } from "@/components/common/page-header";
import { ImportPlaylistDialog } from "@/components/playlists/import-dialog";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { useDeletePlaylist, usePlaylists, useRefreshPlaylist } from "@/hooks/queries";
import { formatRelative, hostOf } from "@/lib/format";

export default function PlaylistsPage() {
  const [importOpen, setImportOpen] = useState(false);
  const router = useRouter();
  const playlists = usePlaylists();
  const refresh = useRefreshPlaylist();
  const del = useDeletePlaylist();

  return (
    <>
      <PageHeader
        title="Playlist"
        subtitle="IPTV e liste M3U"
        actions={
          <Button onClick={() => setImportOpen(true)} className="gap-1.5 rounded-xl" aria-label="Importa playlist">
            <Plus className="size-4" />
            <span className="hidden sm:inline">Importa</span>
          </Button>
        }
      />
      <PageBody className="pt-2">
        {playlists.isLoading ? (
          <div className="grid gap-3 sm:grid-cols-2">
            {Array.from({ length: 4 }, (_, i) => (
              <div key={i} className="h-24 animate-pulse rounded-2xl bg-muted" />
            ))}
          </div>
        ) : !playlists.data?.length ? (
          <EmptyState
            icon={ListVideo}
            title="Nessuna playlist"
            description="Importa una lista M3U dal tuo provider IPTV per vedere i canali e trasmetterli con un tocco."
            action={
              <Button onClick={() => setImportOpen(true)} size="lg" className="gap-1.5 rounded-xl">
                <Plus className="size-4" /> Importa playlist
              </Button>
            }
          />
        ) : (
          // minmax(0,1fr) tracks + min-w-0 items: otherwise the nowrap `truncate` lines set the card's
          // min-content width and the card (with its ⋮ button) overflows narrow phones
          <ul className="grid grid-cols-[minmax(0,1fr)] gap-3 sm:grid-cols-2" data-testid="playlist-grid">
            {playlists.data.map((p) => (
              <li
                key={p.id}
                className="flex min-w-0 items-center gap-1 rounded-2xl border bg-card pr-1 shadow-sm transition hover:border-primary/40"
              >
                <Link href={`/playlists/view/?id=${encodeURIComponent(p.id)}`} className="flex min-h-22 min-w-0 flex-1 items-center gap-3 p-4">
                  <div className="grid size-12 shrink-0 place-items-center rounded-xl bg-primary/12 text-primary">
                    <ListVideo className="size-6" />
                  </div>
                  <div className="min-w-0">
                    <p className="truncate font-semibold">{p.name}</p>
                    <p className="text-sm text-muted-foreground">
                      {p.channel_count.toLocaleString("it")} canali · {p.groups.length} gruppi
                    </p>
                    <p className="truncate text-xs text-muted-foreground/80">
                      {p.source_url ? hostOf(p.source_url) : "da file"} · aggiornata {formatRelative(p.updated_at)}
                    </p>
                  </div>
                </Link>
                <DropdownMenu>
                  <DropdownMenuTrigger render={<Button variant="ghost" size="icon" aria-label={`Azioni per ${p.name}`} />}>
                    <MoreVertical className="size-4" />
                  </DropdownMenuTrigger>
                  <DropdownMenuContent align="end" className="w-48">
                    {p.source_url && (
                      <DropdownMenuItem onClick={() => refresh.mutate(p.id)}>
                        <RefreshCw className="size-4" /> Aggiorna
                      </DropdownMenuItem>
                    )}
                    <DropdownMenuSeparator />
                    <DropdownMenuItem
                      variant="destructive"
                      onClick={() => {
                        if (window.confirm(`Eliminare “${p.name}”?`)) del.mutate(p.id);
                      }}
                    >
                      <Trash2 className="size-4" /> Elimina
                    </DropdownMenuItem>
                  </DropdownMenuContent>
                </DropdownMenu>
              </li>
            ))}
          </ul>
        )}
      </PageBody>
      <ImportPlaylistDialog
        open={importOpen}
        onOpenChange={setImportOpen}
        onImported={(p) => router.push(`/playlists/view/?id=${encodeURIComponent(p.id)}`)}
      />
    </>
  );
}
