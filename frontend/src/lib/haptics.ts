/**
 * Light haptic tick where supported (Android Chrome). iOS Safari ignores it silently.
 *
 * Skipped until the user has interacted with the page: Chromium blocks `navigator.vibrate` before the
 * first tap and logs a console error for each call (e.g. a stream detected while resuming a session).
 */
export function haptic(pattern: number | number[] = 8): void {
  try {
    if (typeof navigator === "undefined" || !("vibrate" in navigator)) return;
    const activation = navigator.userActivation as UserActivation | undefined; // missing in older Safari/Firefox
    if (activation && !activation.hasBeenActive) return;
    navigator.vibrate(pattern);
  } catch {
    /* ignore */
  }
}
