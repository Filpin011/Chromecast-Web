"use client";

import { useInfiniteQuery } from "@tanstack/react-query";
import { ChevronLeft, LayoutGrid, List, Search, SearchX, X } from "lucide-react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { Suspense, useCallback, useMemo, useState } from "react";
import { EmptyState } from "@/components/common/empty-state";
import { PageBody } from "@/components/common/page-header";
import { DeviceButton } from "@/components/devices/device-button";
import { ChannelList, type ChannelAction } from "@/components/playlists/channel-list";
import { ChannelPreviewDialog } from "@/components/playlists/channel-preview-dialog";
import { Button } from "@/components/ui/button";
import { useAddFavorite, usePlaylist } from "@/hooks/queries";
import { channelRequest, useCast } from "@/hooks/use-cast";
import { useDebounced } from "@/hooks/use-debounced";
import { api } from "@/lib/api";
import type { Channel } from "@/lib/api/types";
import { channelInput, preferredChannelLayout, type ChannelLayout } from "@/lib/channels";
import { qk } from "@/lib/query";
import { readStorage, writeStorage } from "@/lib/storage";
import { useT } from "@/i18n";
import { cn } from "@/lib/utils";

const PAGE = 200;
const LAYOUT_KEY = "cw.channels.layout";

function PlaylistView() {
  const t = useT();
  const id = useSearchParams().get("id");
  const playlist = usePlaylist(id);
  const [q, setQ] = useState("");
  const [group, setGroup] = useState<string | null>(null);
  // null = the user never picked one: follow the channels (see preferredChannelLayout)
  const [chosenLayout, setChosenLayout] = useState<ChannelLayout | null>(() => {
    const v = readStorage(LAYOUT_KEY);
    return v === "list" || v === "grid" ? v : null;
  });
  const [preview, setPreview] = useState<Channel | null>(null);
  const debouncedQ = useDebounced(q.trim(), 250);
  const { cast, busy } = useCast();
  const addFavorite = useAddFavorite();

  const channels = useInfiniteQuery({
    queryKey: qk.channels(id ?? "", debouncedQ, group),
    queryFn: ({ pageParam, signal }) =>
      api.playlists.channels(id as string, { q: debouncedQ || undefined, group, offset: pageParam, limit: PAGE }, signal),
    initialPageParam: 0,
    getNextPageParam: (last, pages) => {
      const loaded = pages.reduce((n, p) => n + p.items.length, 0);
      return loaded < last.total && last.items.length > 0 ? loaded : undefined;
    },
    enabled: !!id,
  });

  const pages = useMemo(() => channels.data?.pages ?? [], [channels.data]);
  const total = pages[0]?.total ?? 0;
  const loaded = pages.reduce((n, p) => n + p.items.length, 0);
  const getItem = useCallback((i: number) => pages[Math.floor(i / PAGE)]?.items[i % PAGE], [pages]);
  const { hasNextPage, isFetchingNextPage, fetchNextPage } = channels;
  const needMore = useCallback(() => {
    if (hasNextPage && !isFetchingNextPage) void fetchNextPage();
  }, [hasNextPage, isFetchingNextPage, fetchNextPage]);

  // Decided once, from the first page that loads, so it doesn't flip while searching or paging.
  const firstPage = pages[0]?.items;
  const [autoLayout, setAutoLayout] = useState<ChannelLayout | null>(null);
  if (autoLayout === null && firstPage) setAutoLayout(preferredChannelLayout(firstPage));
  const layout = chosenLayout ?? autoLayout ?? "list";
  const setLayout = (l: ChannelLayout) => {
    setChosenLayout(l);
    writeStorage(LAYOUT_KEY, l);
  };

  const onAction = (action: ChannelAction, c: Channel) => {
    if (action === "queue") void cast(channelRequest(c, true));
    else if (action === "preview") setPreview(c);
    else addFavorite.mutate({ title: c.name, input: channelInput(c), source_kind: "direct", thumbnail: c.logo });
  };

  const groups = playlist.data?.groups ?? [];

  return (
    <>
      <header className="sticky top-0 z-30 bg-background/80 pt-safe backdrop-blur-xl supports-backdrop-filter:bg-background/65">
        <div className="mx-auto flex h-14 max-w-5xl items-center gap-1 px-2 md:px-6">
          <Button variant="ghost" size="icon" aria-label={t("common.back")} render={<Link href="/playlists/" />} nativeButton={false}>
            <ChevronLeft className="size-6" />
          </Button>
          <div className="min-w-0 flex-1">
            <h1 className="truncate text-lg font-bold">{playlist.data?.name ?? t("playlists.fallbackName")}</h1>
            <p className="text-xs text-muted-foreground tabular-nums">
              {channels.isSuccess ? t.plural("playlists.channels", total) : "…"}
            </p>
          </div>
          <Button
            variant="ghost"
            size="icon"
            aria-label={layout === "grid" ? t("playlists.listView") : t("playlists.gridView")}
            onClick={() => setLayout(layout === "grid" ? "list" : "grid")}
          >
            {layout === "grid" ? <List className="size-5" /> : <LayoutGrid className="size-5" />}
          </Button>
          <DeviceButton className="md:hidden" />
        </div>
        <div className="mx-auto max-w-5xl space-y-2 px-4 pb-2 md:px-8">
          <div className="relative">
            <Search className="pointer-events-none absolute top-1/2 left-3.5 size-4 -translate-y-1/2 text-muted-foreground" />
            <input
              type="search"
              aria-label={t("playlists.searchChannel")}
              value={q}
              onChange={(e) => setQ(e.target.value)}
              placeholder={t("playlists.searchChannel")}
              className="h-11 w-full rounded-xl bg-muted pr-10 pl-10 text-base outline-none focus:ring-2 focus:ring-primary/40"
            />
            {q && (
              <button type="button" aria-label={t("common.clearSearch")} onClick={() => setQ("")} className="absolute top-1/2 right-1 grid size-9 -translate-y-1/2 place-items-center text-muted-foreground">
                <X className="size-4" />
              </button>
            )}
          </div>
          {groups.length > 0 && (
            <div className="-mx-4 flex gap-2 overflow-x-auto px-4 no-scrollbar md:-mx-8 md:px-8" role="radiogroup" aria-label={t("playlists.groupsLabel")}>
              {[null, ...groups].map((g) => (
                <button
                  key={g ?? "__all"}
                  type="button"
                  role="radio"
                  aria-checked={group === g}
                  onClick={() => setGroup(g)}
                  className={cn(
                    "h-8 shrink-0 rounded-full border px-3.5 text-xs font-medium whitespace-nowrap transition-colors",
                    group === g ? "border-primary bg-primary text-primary-foreground" : "bg-card text-muted-foreground",
                  )}
                >
                  {g ?? t("playlists.allGroups")}
                </button>
              ))}
            </div>
          )}
        </div>
      </header>
      <PageBody className="pt-2">
        {!id ? (
          <EmptyState icon={SearchX} title={t("errors.playlist_not_found")} />
        ) : channels.isError ? (
          <EmptyState icon={SearchX} title={t("playlists.loadFailed")} description={t("playlists.loadFailedHint")} />
        ) : channels.isSuccess && total === 0 ? (
          <EmptyState icon={SearchX} title={t("playlists.noChannels")} description={q ? t("playlists.noResultsFor", { q }) : undefined} />
        ) : (
          <ChannelList
            key={`${layout}-${debouncedQ}-${group}`}
            total={channels.isSuccess ? total : 24}
            loaded={loaded}
            getItem={getItem}
            layout={layout}
            disabled={busy}
            onNeedMore={needMore}
            onSelect={(c) => cast(channelRequest(c))}
            onAction={onAction}
          />
        )}
      </PageBody>
      <ChannelPreviewDialog
        channel={preview}
        onOpenChange={(open) => !open && setPreview(null)}
        busy={busy}
        onCast={(c) => {
          setPreview(null);
          void cast(channelRequest(c));
        }}
        onQueue={(c) => void cast(channelRequest(c, true))}
      />
    </>
  );
}

export default function PlaylistViewPage() {
  return (
    <Suspense fallback={null}>
      <PlaylistView />
    </Suspense>
  );
}
