import { formatDate, t } from "@/i18n";
import { stripExtension } from "@/lib/format";

/**
 * The name an M3U text gives itself: `#PLAYLIST:<name>`, or the `x-tvg-name` / `name` attribute of the
 * `#EXTM3U` header (what the backend reads). Null when it has none.
 */
export function embeddedPlaylistName(content: string): string | null {
  for (const raw of content.replace(/^﻿/, "").split(/\r?\n/)) {
    const line = raw.trim();
    if (line.startsWith("#EXTM3U")) {
      const m = /\b(?:x-tvg-name|name)="([^"]*)"/i.exec(line);
      if (m?.[1]?.trim()) return m[1].trim();
    } else if (/^#PLAYLIST:/i.test(line)) {
      const v = line.slice("#PLAYLIST:".length).trim();
      if (v) return v;
    }
  }
  return null;
}

/**
 * Name of a playlist imported from a file or pasted text: what the user typed, else the name in the
 * text, else the file name without its extension, else "Playlist <date>" (never a bare "Playlist").
 */
export function importedPlaylistName({
  typed,
  content,
  fileName,
  now = new Date(),
}: {
  typed?: string;
  content: string;
  fileName?: string | null;
  now?: Date;
}): string {
  return (
    typed?.trim() ||
    embeddedPlaylistName(content) ||
    (fileName ? stripExtension(fileName) : "") ||
    t("import.defaultName", { date: formatDate(now) })
  );
}
