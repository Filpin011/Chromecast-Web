/** Heuristics for choosing how to play a URL in the browser preview. */
export function isHlsSource(url: string, mime?: string | null): boolean {
  if (mime && /mpegurl/i.test(mime)) return true;
  return /\.m3u8(\?|#|$)/i.test(url) || /\/proxy\/[^/]+\/.*m3u8/i.test(url);
}

export function isDashSource(url: string, mime?: string | null): boolean {
  if (mime && /dash\+xml/i.test(mime)) return true;
  return /\.mpd(\?|#|$)/i.test(url);
}

export function canPlayNativeHls(video: HTMLVideoElement): boolean {
  return !!video.canPlayType("application/vnd.apple.mpegurl");
}
