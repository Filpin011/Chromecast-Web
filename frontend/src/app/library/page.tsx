"use client";

import { ChevronRight, Clock, FolderOpen, Star, Trash2 } from "lucide-react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useMemo } from "react";
import { EmptyState } from "@/components/common/empty-state";
import { PageBody, PageHeader } from "@/components/common/page-header";
import { MediaRow, MediaRowSkeleton } from "@/components/library/media-row";
import { Button } from "@/components/ui/button";
import {
  useAddFavorite,
  useClearHistory,
  useFavorites,
  useHistory,
  useLocalAvailable,
  useRemoveFavorite,
} from "@/hooks/queries";
import { useDevices } from "@/hooks/use-app-state";
import { useCast } from "@/hooks/use-cast";
import { formatRelative, SOURCE_LABEL } from "@/lib/format";
import { cn } from "@/lib/utils";

type Tab = "favorites" | "history";

function LibraryInner() {
  const params = useSearchParams();
  const router = useRouter();
  const tab: Tab = params.get("tab") === "history" ? "history" : "favorites";
  const favorites = useFavorites();
  const history = useHistory(100);
  const removeFav = useRemoveFavorite();
  const addFav = useAddFavorite();
  const clear = useClearHistory();
  const { cast, busy } = useCast();
  const devices = useDevices();
  const localAvailable = useLocalAvailable();
  const names = useMemo(() => new Map(devices.map((d) => [d.id, d.name])), [devices]);
  const deviceName = (id: string | null) => (id ? names.get(id) : undefined);

  const setTab = (t: Tab) => router.replace(`/library/?tab=${t}`, { scroll: false });
  const list = tab === "favorites" ? favorites : history;

  return (
    <>
      <PageHeader
        title="Libreria"
        actions={
          tab === "history" && (history.data?.length ?? 0) > 0 ? (
            <Button
              variant="ghost"
              size="icon"
              aria-label="Cancella cronologia"
              onClick={() => {
                if (window.confirm("Cancellare tutta la cronologia?")) clear.mutate();
              }}
            >
              <Trash2 className="size-5" />
            </Button>
          ) : null
        }
      />
      <PageBody className="space-y-4 pt-2">
        {localAvailable && (
          <Link href="/files/" className="flex min-h-14 items-center gap-3 rounded-2xl border bg-card px-4 md:hidden">
            <FolderOpen className="size-5 text-primary" />
            <span className="flex-1 font-medium">File locali</span>
            <ChevronRight className="size-4 text-muted-foreground" />
          </Link>
        )}
        <div className="grid grid-cols-2 gap-1 rounded-xl bg-muted p-1" role="tablist">
          {(
            [
              ["favorites", Star, "Preferiti", favorites.data?.length],
              ["history", Clock, "Cronologia", history.data?.length],
            ] as const
          ).map(([t, Icon, label, count]) => (
            <button
              key={t}
              type="button"
              role="tab"
              aria-selected={tab === t}
              onClick={() => setTab(t)}
              className={cn(
                "flex h-10 items-center justify-center gap-1.5 rounded-lg text-sm font-medium transition-all",
                tab === t ? "bg-background shadow-sm" : "text-muted-foreground",
              )}
            >
              <Icon className="size-4" /> {label}
              {count ? <span className="text-xs text-muted-foreground tabular-nums">{count}</span> : null}
            </button>
          ))}
        </div>

        <div className="rounded-2xl border bg-card p-1">
          {list.isLoading ? (
            Array.from({ length: 5 }, (_, i) => <MediaRowSkeleton key={i} />)
          ) : tab === "favorites" ? (
            favorites.data?.length ? (
              favorites.data.map((f) => (
                <MediaRow
                  key={f.id}
                  title={f.title}
                  subtitle={`${SOURCE_LABEL[f.source_kind]} · ${formatRelative(f.created_at)}`}
                  thumbnail={f.thumbnail}
                  disabled={busy}
                  onCast={() => cast({ input: f.input, kind: f.source_kind, title: f.title })}
                  onQueue={() => cast({ input: f.input, kind: f.source_kind, title: f.title, enqueue: true })}
                  onDelete={() => removeFav.mutate(f.id)}
                />
              ))
            ) : (
              <EmptyState icon={Star} title="Nessun preferito" description="Tocca la stella su un contenuto per ritrovarlo qui." />
            )
          ) : history.data?.length ? (
            history.data.map((h) => (
              <MediaRow
                key={h.id}
                title={h.title}
                subtitle={[SOURCE_LABEL[h.source_kind], deviceName(h.device_id), formatRelative(h.played_at)].filter(Boolean).join(" · ")}
                thumbnail={h.thumbnail}
                disabled={busy}
                onCast={() => cast({ input: h.input, kind: h.source_kind, title: h.title })}
                onQueue={() => cast({ input: h.input, kind: h.source_kind, title: h.title, enqueue: true })}
                onFavorite={() => addFav.mutate({ title: h.title, input: h.input, source_kind: h.source_kind, thumbnail: h.thumbnail })}
              />
            ))
          ) : (
            <EmptyState icon={Clock} title="Cronologia vuota" description="Ciò che trasmetti comparirà qui." />
          )}
        </div>
      </PageBody>
    </>
  );
}

export default function LibraryPage() {
  return (
    <Suspense fallback={null}>
      <LibraryInner />
    </Suspense>
  );
}
