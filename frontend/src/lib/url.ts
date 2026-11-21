/** Turn what the user typed into an http(s) URL, or null. Bare words become a search. */
export function normalizeUrl(raw: string): string | null {
  const v = raw.trim();
  if (!v) return null;
  if (/^https?:\/\//i.test(v)) return v;
  if (/^\d{1,3}(\.\d{1,3}){3}(:\d+)?(\/\S*)?$/.test(v)) return `http://${v}`;
  if (/^[\w-]+(\.[\w-]+)+(:\d+)?(\/\S*)?$/.test(v) || /^localhost(:\d+)?(\/\S*)?$/.test(v)) return `https://${v}`;
  return `https://duckduckgo.com/?q=${encodeURIComponent(v)}`;
}

/**
 * Whether `raw` is an absolute http(s) URL with a host and no whitespace: what the backend accepts for
 * the settings the Chromecast fetches (idle image, public base URL). Mirrors `SettingsUpdate._http_url`.
 */
export function isHttpUrl(raw: string): boolean {
  const v = raw.trim();
  if (!v || /\s/.test(v)) return false;
  try {
    const u = new URL(v);
    return (u.protocol === "http:" || u.protocol === "https:") && !!u.hostname;
  } catch {
    return false;
  }
}
