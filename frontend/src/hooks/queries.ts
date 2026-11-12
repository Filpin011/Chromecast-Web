"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { api, ApiError } from "@/lib/api";
import type { FavoriteCreate, PlaylistImportRequest, Settings } from "@/lib/api/types";
import { currentTranslator, t } from "@/i18n";
import { errorMessage, qk } from "@/lib/query";

export function useHealth() {
  return useQuery({ queryKey: qk.health, queryFn: () => api.system.health(), staleTime: 60_000 });
}

/* ---------------- playlists ---------------- */

export function usePlaylists() {
  return useQuery({ queryKey: qk.playlists, queryFn: () => api.playlists.list() });
}

export function usePlaylist(id: string | null) {
  return useQuery({
    queryKey: qk.playlist(id ?? ""),
    queryFn: () => api.playlists.get(id as string),
    enabled: !!id,
  });
}

export function useImportPlaylist() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (req: PlaylistImportRequest) => api.playlists.import(req),
    onSuccess: (p) => {
      qc.invalidateQueries({ queryKey: qk.playlists });
      toast.success(t("playlists.imported", { name: p.name }), { description: currentTranslator().plural("playlists.channels", p.channel_count) });
    },
    onError: (e) => toast.error(errorMessage(e, t("playlists.importFailed"))),
  });
}

export function useRefreshPlaylist() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => api.playlists.refresh(id),
    onSuccess: (p) => {
      qc.invalidateQueries({ queryKey: qk.playlists });
      toast.success(t("playlists.refreshed", { name: p.name }), { description: currentTranslator().plural("playlists.channels", p.channel_count) });
    },
    onError: (e) => toast.error(errorMessage(e, t("playlists.refreshFailed"))),
  });
}

export function useDeletePlaylist() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => api.playlists.remove(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: qk.playlists }),
    onError: (e) => toast.error(errorMessage(e)),
  });
}

/* ---------------- favorites & history ---------------- */

export function useFavorites() {
  return useQuery({ queryKey: qk.favorites, queryFn: () => api.favorites.list() });
}

export function useAddFavorite() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (req: FavoriteCreate) => api.favorites.add(req),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: qk.favorites });
      toast.success(t("toast.addedToFavorites"));
    },
    onError: (e) => toast.error(errorMessage(e)),
  });
}

export function useRemoveFavorite() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => api.favorites.remove(id),
    onMutate: async (id) => {
      await qc.cancelQueries({ queryKey: qk.favorites });
      const prev = qc.getQueryData<import("@/lib/api/types").Favorite[]>(qk.favorites);
      if (prev) qc.setQueryData(qk.favorites, prev.filter((f) => f.id !== id));
      return { prev };
    },
    onError: (e, _id, ctx) => {
      if (ctx?.prev) qc.setQueryData(qk.favorites, ctx.prev);
      toast.error(errorMessage(e));
    },
    onSettled: () => qc.invalidateQueries({ queryKey: qk.favorites }),
  });
}

export function useHistory(limit = 50) {
  return useQuery({ queryKey: [...qk.history, limit], queryFn: () => api.history.list(limit) });
}

export function useClearHistory() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => api.history.clear(),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: qk.history });
      toast.success(t("library.historyCleared"));
    },
    onError: (e) => toast.error(errorMessage(e)),
  });
}

/* ---------------- settings ---------------- */

export function useSettings() {
  return useQuery({ queryKey: qk.settings, queryFn: () => api.settings.get() });
}

export function useUpdateSettings() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (patch: Partial<Settings>) => api.settings.update(patch),
    onMutate: async (patch) => {
      await qc.cancelQueries({ queryKey: qk.settings });
      const prev = qc.getQueryData<Settings>(qk.settings);
      if (prev) qc.setQueryData(qk.settings, { ...prev, ...patch });
      return { prev };
    },
    onError: (e, _p, ctx) => {
      if (ctx?.prev) qc.setQueryData(qk.settings, ctx.prev);
      toast.error(errorMessage(e, t("settings.saveFailed")));
    },
    onSuccess: (s) => qc.setQueryData(qk.settings, s),
  });
}

/* ---------------- local files ---------------- */

export function useLocalListing(path: string) {
  return useQuery({ queryKey: qk.local(path), queryFn: () => api.local.list(path) });
}

/** `false` when the backend has no MEDIA_ROOT (404 local_disabled). `undefined` while unknown. */
export function useLocalAvailable(): boolean | undefined {
  const q = useQuery({
    queryKey: qk.local(""),
    queryFn: () => api.local.list(""),
    staleTime: 5 * 60_000,
    refetchOnWindowFocus: false,
  });
  if (q.isSuccess) return true;
  if (q.isError) return !(q.error instanceof ApiError && (q.error.code === "local_disabled" || q.error.status === 404));
  return undefined;
}
