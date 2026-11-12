"use client";

import { useQuery } from "@tanstack/react-query";
import { Clock, Compass, Sparkles, Star } from "lucide-react";
import { AnimatePresence } from "motion/react";
import Link from "next/link";
import { useState } from "react";
import { MediaResultCard, PlaylistResultCard, ResolveErrorCard, ResultSkeleton } from "@/components/cast/result-card";
import { SmartInput } from "@/components/cast/smart-input";
import { PageBody, PageHeader } from "@/components/common/page-header";
import { Thumb } from "@/components/common/thumb";
import { MediaRow, MediaRowSkeleton } from "@/components/library/media-row";
import { Button } from "@/components/ui/button";
import { useAddFavorite, useFavorites, useHistory } from "@/hooks/queries";
import { useCast } from "@/hooks/use-cast";
import { useDebounced } from "@/hooks/use-debounced";
import { api } from "@/lib/api";
import { formatRelative, SOURCE_LABEL_KEY } from "@/lib/format";
import { useT } from "@/i18n";
import { autoResolvesWhileTyping, detectInput } from "@/lib/input-detect";

function Section({ title, icon: Icon, href, children }: { title: string; icon: typeof Clock; href?: string; children: React.ReactNode }) {
  const t = useT();
  return (
    <section className="space-y-2">
      <div className="flex items-center justify-between px-1">
        <h2 className="flex items-center gap-2 text-sm font-semibold text-muted-foreground">
          <Icon className="size-4" /> {title}
        </h2>
        {href && (
          // 44px touch target; the negative margin keeps the header row at text height
          <Link href={href} className="-my-3 -mr-2 inline-flex min-h-11 items-center px-2 text-sm font-medium text-primary">
            {t("common.seeAll")}
          </Link>
        )}
      </div>
      {children}
    </section>
  );
}

export default function CastPage() {
  const [input, setInput] = useState("");
  const [submitted, setSubmitted] = useState<string | null>(null);
  const debounced = useDebounced(input.trim(), 700);
  const t = useT();
  const { cast, busy } = useCast();
  const addFav = useAddFavorite();

  // Resolve on submit or paste; while typing only cheap inputs (direct streams, M3U) auto-resolve after a pause,
  // so half-typed page URLs don't start a headless-browser resolve on the server.
  const typed = detectInput(debounced);
  const target = submitted ?? (autoResolvesWhileTyping(typed) ? debounced : "");
  const detected = detectInput(target);
  const resolvable = detected.kind !== "empty" && detected.kind !== "invalid" && target === input.trim();
  const current = detectInput(input);
  const needsSubmit = !resolvable && !autoResolvesWhileTyping(current);
  const resolve = useQuery({
    queryKey: ["resolve", detected.value, detected.sourceKind ?? null],
    queryFn: ({ signal }) => api.resolver.resolve(detected.value, detected.sourceKind, signal),
    enabled: resolvable,
    staleTime: 5 * 60_000,
    retry: false,
    refetchOnWindowFocus: false,
  });

  const history = useHistory(6);
  const favorites = useFavorites();

  return (
    <>
      <PageHeader title={t("cast.title")} subtitle={t("cast.subtitle")} />
      <PageBody className="space-y-8 pt-2">
        <div className="space-y-4">
          <SmartInput
            value={input}
            onChange={(v, source) => {
              setInput(v);
              // a paste is complete input: resolve it right away
              setSubmitted(source === "paste" && v.trim() ? v.trim() : null);
            }}
            onSubmit={(v) => setSubmitted(v)}
            loading={resolve.isFetching}
            autoFocus={false}
            hint={needsSubmit ? t("cast.pressEnter") : null}
          />
          <AnimatePresence mode="wait">
            {resolvable && resolve.isFetching && !resolve.data ? (
              <ResultSkeleton key="sk" />
            ) : resolvable && resolve.isError ? (
              <ResolveErrorCard
                key="err"
                error={resolve.error}
                input={detected.value}
                onRetry={() => void resolve.refetch()}
                retrying={resolve.isFetching}
              />
            ) : resolvable && resolve.data?.type === "media" ? (
              <MediaResultCard key={`m-${resolve.data.media.original_input}`} media={resolve.data.media} />
            ) : resolvable && resolve.data?.type === "playlist" ? (
              <PlaylistResultCard key="pl" name={resolve.data.name} channels={resolve.data.channels} input={detected.value} />
            ) : null}
          </AnimatePresence>
          {!input && (
            <div className="grid grid-cols-2 gap-2 sm:grid-cols-3">
              <Button variant="outline" size="lg" className="justify-start gap-2 rounded-xl" render={<Link href="/browser/" />} nativeButton={false}>
                <Compass className="size-5 text-primary" /> {t("nav.browser")}
              </Button>
              <Button variant="outline" size="lg" className="justify-start gap-2 rounded-xl" render={<Link href="/playlists/" />} nativeButton={false}>
                <Sparkles className="size-5 text-primary" /> {t("cast.iptvPlaylists")}
              </Button>
            </div>
          )}
        </div>

        {(history.isLoading || (history.data?.length ?? 0) > 0) && (
          <Section title={t("cast.recent")} icon={Clock} href="/library/?tab=history">
            <div className="rounded-2xl border bg-card p-1">
              {history.isLoading
                ? Array.from({ length: 3 }, (_, i) => <MediaRowSkeleton key={i} />)
                : history.data?.map((h) => (
                    <MediaRow
                      key={h.id}
                      title={h.title}
                      subtitle={`${t(SOURCE_LABEL_KEY[h.source_kind])} · ${formatRelative(h.played_at)}`}
                      thumbnail={h.thumbnail}
                      disabled={busy}
                      onCast={() => cast({ input: h.input, kind: h.source_kind, title: h.title })}
                      onQueue={() => cast({ input: h.input, kind: h.source_kind, title: h.title, enqueue: true })}
                      onFavorite={() =>
                        addFav.mutate({ title: h.title, input: h.input, source_kind: h.source_kind, thumbnail: h.thumbnail })
                      }
                    />
                  ))}
            </div>
          </Section>
        )}

        {(favorites.data?.length ?? 0) > 0 && (
          <Section title={t("cast.favorites")} icon={Star} href="/library/?tab=favorites">
            <div className="-mx-4 flex snap-x gap-3 overflow-x-auto px-4 pb-1 no-scrollbar md:mx-0 md:px-0">
              {favorites.data?.slice(0, 12).map((f) => (
                <button
                  key={f.id}
                  type="button"
                  disabled={busy}
                  onClick={() => cast({ input: f.input, kind: f.source_kind, title: f.title })}
                  className="w-40 shrink-0 snap-start space-y-1.5 text-left active:scale-[0.98]"
                >
                  <Thumb src={f.thumbnail} className="aspect-video w-full rounded-xl" />
                  <p className="line-clamp-2 text-xs font-medium">{f.title}</p>
                </button>
              ))}
            </div>
          </Section>
        )}
      </PageBody>
    </>
  );
}
