## What does this change?

<!-- Short description. PR title = Conventional Commit, e.g. "fix: resume HLS proxy after Chromecast reconnect". -->

## Checklist

- [ ] Backend: `pytest -q` and `ruff check .` pass (in `backend/`)
- [ ] Frontend: `npm run typecheck`, `npm run lint`, `npm test`, `npm run build` pass (in `frontend/`)
- [ ] `docs/ARCHITECTURE.md` updated first if models, endpoints or WebSocket messages changed
- [ ] Tests added or updated for the change
- [ ] Checked in the app (fake driver or a real Chromecast) – screenshots attached for visual changes (phone width,
      light and dark)
- [ ] English and Italian texts updated (`frontend/src/i18n`)
- [ ] No private data (IPs, stream URLs, credentials, playlists, tokens) in code or screenshots
