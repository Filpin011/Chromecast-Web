"use client";

import { ChevronRight, File, FileVideo, Folder, FolderX, HardDrive, Music } from "lucide-react";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense } from "react";
import { EmptyState } from "@/components/common/empty-state";
import { PageBody, PageHeader } from "@/components/common/page-header";
import { MediaRowSkeleton } from "@/components/library/media-row";
import { useLocalListing } from "@/hooks/queries";
import { useCast } from "@/hooks/use-cast";
import { ApiError } from "@/lib/api";
import type { LocalEntry } from "@/lib/api/types";
import { formatBytes } from "@/lib/format";

function iconFor(e: LocalEntry) {
  if (e.is_dir) return Folder;
  if (e.mime_type?.startsWith("video/")) return FileVideo;
  if (e.mime_type?.startsWith("audio/")) return Music;
  return File;
}

function FilesInner() {
  const router = useRouter();
  const path = useSearchParams().get("path") ?? "";
  const listing = useLocalListing(path);
  const { cast, busy } = useCast();
  const go = (p: string) => router.push(p ? `/files/?path=${encodeURIComponent(p)}` : "/files/");
  const crumbs = path.split("/").filter(Boolean);
  const disabled = listing.error instanceof ApiError && (listing.error.code === "local_disabled" || listing.error.status === 404) && !path;

  return (
    <>
      <PageHeader title="File locali" subtitle="Media sul server" />
      <PageBody className="space-y-3 pt-2">
        {disabled ? (
          <EmptyState
            icon={HardDrive}
            title="File locali non attivi"
            description="Imposta MEDIA_ROOT sul server per sfogliare e trasmettere i tuoi file."
          />
        ) : (
          <>
            <nav aria-label="Percorso" className="-mx-4 flex items-center gap-1 overflow-x-auto px-4 text-sm no-scrollbar">
              <button type="button" onClick={() => go("")} className="h-9 shrink-0 rounded-lg px-2 font-medium text-primary">
                Media
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
                Array.from({ length: 6 }, (_, i) => <MediaRowSkeleton key={i} />)
              ) : listing.isError ? (
                <EmptyState icon={FolderX} title="Cartella non accessibile" />
              ) : !listing.data?.entries.length ? (
                <EmptyState icon={Folder} title="Cartella vuota" />
              ) : (
                listing.data.entries.map((e) => {
                  const Icon = iconFor(e);
                  return (
                    <button
                      key={e.path}
                      type="button"
                      disabled={!e.is_dir && busy}
                      onClick={() => (e.is_dir ? go(e.path) : cast({ input: e.path, kind: "local", title: e.name }))}
                      className="flex min-h-14 w-full items-center gap-3 rounded-xl px-3 text-left active:bg-muted"
                    >
                      <Icon className={e.is_dir ? "size-5 text-primary" : "size-5 text-muted-foreground"} />
                      <span className="min-w-0 flex-1 truncate text-sm font-medium">{e.name}</span>
                      {e.is_dir ? (
                        <ChevronRight className="size-4 text-muted-foreground" />
                      ) : (
                        <span className="text-xs text-muted-foreground tabular-nums">{formatBytes(e.size)}</span>
                      )}
                    </button>
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
