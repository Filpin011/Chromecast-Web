"use client";

import { ChevronRight, File, FileVideo, Folder, FolderX, HardDrive, ListPlus, MonitorPlay, Music, Star } from "lucide-react";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense } from "react";
import { EmptyState } from "@/components/common/empty-state";
import { PageBody, PageHeader } from "@/components/common/page-header";
import { ListRowSkeleton, RowMenu, type RowAction } from "@/components/common/list-row";
import { useAddFavorite, useLocalListing } from "@/hooks/queries";
import { useCast, type CastRequest } from "@/hooks/use-cast";
import { ApiError } from "@/lib/api";
import type { LocalEntry } from "@/lib/api/types";
import { useT } from "@/i18n";
import { formatBytes, stripExtension } from "@/lib/format";
import { resolvedSource, seekAfterCast } from "@/lib/local-player/sources";
import { openLocalPlayer } from "@/stores/local-player-store";

function iconFor(e: LocalEntry) {
  if (e.is_dir) return Folder;
  if (e.mime_type?.startsWith("video/")) return FileVideo;
  if (e.mime_type?.startsWith("audio/")) return Music;
  return File;
}

function FilesInner() {
  const t = useT();
  const router = useRouter();
  const path = useSearchParams().get("path") ?? "";
  const listing = useLocalListing(path);
  const { cast, busy } = useCast();
  const addFavorite = useAddFavorite();
  const go = (p: string) => router.push(p ? `/files/?path=${encodeURIComponent(p)}` : "/files/");
  const crumbs = path.split("/").filter(Boolean);
  const disabled = listing.error instanceof ApiError && (listing.error.code === "local_disabled" || listing.error.status === 404) && !path;

  return (
    <>
      <PageHeader title={t("nav.files")} subtitle={t("files.subtitle")} />
      <PageBody className="space-y-3 pt-2">
        {disabled ? (
          <EmptyState
            icon={HardDrive}
            title={t("files.disabled")}
            description={t("files.disabledHint")}
          />
        ) : (
          <>
            <nav aria-label={t("files.path")} className="-mx-4 flex items-center gap-1 overflow-x-auto px-4 text-sm no-scrollbar">
              <button type="button" onClick={() => go("")} className="h-9 shrink-0 rounded-lg px-2 font-medium text-primary">
                {t("files.root")}
              </button>
              {crumbs.map((c, i) => (
                <span key={i} className="flex shrink-0 items-center gap-1">
                  <ChevronRight className="size-4 text-muted-foreground" />
                  <button
                    type="button"
                    onClick={() => go(crumbs.slice(0, i + 1).join("/"))}
                    className="h-9 rounded-lg px-2 font-medium"
                    aria-current={i === crumbs.length - 1 ? "page" : undefined}
                  >
                    {c}
                  </button>
                </span>
              ))}
            </nav>
            <div className="rounded-2xl border bg-card p-1">
              {listing.isLoading ? (
                Array.from({ length: 6 }, (_, i) => <ListRowSkeleton key={i} />)
              ) : listing.isError ? (
                <EmptyState icon={FolderX} title={t("files.unreadable")} />
              ) : !listing.data?.entries.length ? (
                <EmptyState icon={Folder} title={t("files.empty")} />
              ) : (
                listing.data.entries.map((e) => {
                  const Icon = iconFor(e);
                  const title = stripExtension(e.name);
                  const req = (enqueue = false): CastRequest => ({ input: e.path, kind: "local", title, enqueue });
                  const actions: RowAction[] = e.is_dir
                    ? []
                    : [
                        { label: t("media.addToQueue"), icon: ListPlus, onClick: () => void cast(req(true)) },
                        {
                          label: t("media.addToFavorites"),
                          icon: Star,
                          onClick: () => addFavorite.mutate({ title, input: e.path, source_kind: "local", thumbnail: null }),
                        },
                        {
                          label: t("localPlayer.watchHere"),
                          icon: MonitorPlay,
                          onClick: () =>
                            openLocalPlayer({
                              title,
                              source: resolvedSource(e.path, "local"),
                              onCast: (at) => void cast(req()).then((p) => seekAfterCast(p, at)),
                            }),
                        },
                      ];
                  return (
                    <div key={e.path} className="flex items-center gap-1 rounded-xl">
                      <button
                        type="button"
                        disabled={!e.is_dir && busy}
                        onClick={() => (e.is_dir ? go(e.path) : cast(req()))}
                        aria-label={e.is_dir ? undefined : t("captured.castName", { name: e.name })}
                        className="flex min-h-14 min-w-0 flex-1 items-center gap-3 rounded-xl px-3 text-left active:bg-muted"
                      >
                        <Icon className={e.is_dir ? "size-5 text-primary" : "size-5 text-muted-foreground"} />
                        <span className="min-w-0 flex-1 truncate text-sm font-medium">{e.name}</span>
                        {e.is_dir ? (
                          <ChevronRight className="size-4 text-muted-foreground" />
                        ) : (
                          <span className="text-xs text-muted-foreground tabular-nums">{formatBytes(e.size, t.locale)}</span>
                        )}
                      </button>
                      <RowMenu label={t("playlists.actionsFor", { name: e.name })} actions={actions} />
                    </div>
                  );
                })
              )}
            </div>
          </>
        )}
      </PageBody>
    </>
  );
}

export default function FilesPage() {
  return (
    <Suspense fallback={null}>
      <FilesInner />
    </Suspense>
  );
}
