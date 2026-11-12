# Chromecast Web — frontend

Next.js (App Router, static export) + TypeScript strict + Tailwind v4 + shadcn/ui (Base UI) + lucide.
The contract with the backend is `../docs/ARCHITECTURE.md`.

## Commands

```bash
npm install
NEXT_PUBLIC_API_PORT=8000 npx next dev -H 0.0.0.0   # dev: backend on the page's host, port 8000 (works from a phone on the LAN)
NEXT_PUBLIC_API_BASE=http://localhost:8000 npm run dev  # or a fixed backend URL (takes precedence)
npm run typecheck   # tsc --noEmit
npm run lint        # eslint
npm test            # vitest (jsdom, no backend needed)
npm run build       # static export → out/ (served by FastAPI at /)
```

In production the app is served by the backend on the same origin, so `NEXT_PUBLIC_API_BASE` / `NEXT_PUBLIC_API_PORT` stay unset.
From a phone in dev, the backend must also allow the `http://<lan-ip>:3000` origin (CORS, backend setting).

## Layout

- `src/lib/api` — typed REST client (`api.devices`, `api.player`, `api.browser`, …), `ApiError`, contract types (`types.ts`).
- `src/lib/ws` — `ReconnectingSocket` (backoff + jitter, ping), `StateSocket` (`/ws`), `BrowserSocket` (`/ws/browser/{id}`).
- `src/stores` — zustand: `app-store` (AppState snapshots, version ordering, optimistic overlays), `ui-store` (sheets, `requestDevice()`).
- `src/hooks` — `useActivePlayer`, `useCommand` (optimistic control), `useCast` (device selection + toasts), TanStack Query hooks.
- `src/components` — app shell (tab bar / sidebar, mini player, Now Playing, device sheet), cast, browser, playlists, library.
- `src/app` — pages: `/` (Cast), `/browser`, `/playlists`, `/playlists/view?id=`, `/library`, `/files`, `/settings`.
