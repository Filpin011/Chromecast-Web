# Contributing

Thanks for helping! This is an independent, unofficial project (see [DISCLAIMER.md](DISCLAIMER.md)).

## Workflow

- `main` is protected: changes go through pull requests with green checks (backend `pytest` + `ruff`, frontend
  `typecheck` / `lint` / `test` / `build`, Docker image build for `linux/amd64` + `linux/arm64` with container smoke
  tests, CodeQL).
- Commit messages and PR titles follow [Conventional Commits](https://www.conventionalcommits.org/); squash-merge.
- [release-please](https://github.com/googleapis/release-please) keeps a release PR that bumps the version (in
  `backend/pyproject.toml`, `backend/app/__init__.py`, `frontend/package.json` and `frontend/package-lock.json`) and
  updates `CHANGELOG.md`. Merging it tags `vX.Y.Z`; the release workflow then builds the multi-arch Docker image
  (`linux/amd64`, `linux/arm64`) and publishes it to GHCR as `ghcr.io/filpin011/chromecast-web:X.Y.Z` and `:latest`.

## Releases

- **First release**: `.release-please-manifest.json` holds `0.0.0` (nothing released yet) and the package sets
  `"initial-version": "0.1.0"`, so the first release PR is `0.1.0`, not a bump past an unreleased `0.1.0`. Both
  settings are inert once `v0.1.0` exists; leave them as they are.
- **GHCR visibility (once, after the first release)**: a new GHCR package is created **private**, even for a public
  repository, so `docker pull` / Coolify without a GHCR login get `unauthorized`. On GitHub open *Packages ›
  chromecast-web › Package settings*, set the visibility to **Public** and check that the package is linked to this
  repository (the image's `org.opencontainers.image.source` label links it automatically).
- **Release PR checks (once)**: GitHub starts no workflows for pull requests opened with the default
  `GITHUB_TOKEN`, so the release PR would wait forever for `main`'s required checks. Add a repository secret
  `RELEASE_PLEASE_TOKEN` (fine-grained personal access token or GitHub App token limited to this repository, with
  *Contents*, *Pull requests* and *Issues* read/write); the release workflow uses it, and CI and CodeQL then run on
  the release PR like on any other. Without the secret it falls back to `GITHUB_TOKEN`: run *CI* and *CodeQL* by
  hand on the release branch (*Actions › Run workflow* on the release PR's branch, `release-please--branches--main…`) after each update
  of the release PR, then merge once they are green.
- **Re-publishing an image**: run the *Release* workflow manually (`workflow_dispatch`) with an existing tag, e.g.
  `v0.1.0`. It pushes `X.Y.Z` only; check *latest* only when that tag is the newest release, otherwise `:latest`
  would move back to an older version.

## Local setup

Python 3.12+, Node 24+, ffmpeg. `make help` lists every target.

```sh
make setup          # backend/.venv (incl. dev deps) + frontend node_modules
make browsers       # Playwright Chromium: web pages, remote browser and the @browser tests
make dev            # backend with the fake Chromecast (:8000) + Next dev server (:3000), reachable on the LAN
make test           # every check: pytest + ruff, typecheck + lint + vitest + static build
make serve          # production-like: the backend serves the static export on :8000
make demo           # fake Chromecast + fictional demo data on :8000 (backend/scripts/demo.py)
make screenshots    # regenerate docs/screenshots + docs/assets/hero.png from the demo (needs Chromium)
make brand          # re-render icons/favicon/social preview from docs/assets/icon*.svg
```

- **Fake driver** (default for `make dev` / `make serve`): `CAST_DRIVER=fake` simulates Chromecast devices, so the
  whole UI and API work without hardware. Tests never need a real device or network.
- **Real Chromecast**: run on a machine on the same LAN as the device with `CAST_DRIVER=pychromecast make
  dev-backend`. If the Chromecast cannot reach the proxy, set `PUBLIC_BASE_URL=http://<lan-ip>:8000`; if mDNS
  discovery fails, add the device by IP in the app.
- **Docker**: `make docker` builds the image, `make docker-up` starts it with host networking (needed for mDNS and
  so the Chromecast can reach the proxy).

## Guidelines

- Contract first: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) is the single source of truth for models, endpoints
  and WebSocket messages. Change it first, then the backend (`backend/app/models`) and the frontend
  (`frontend/src/lib/api`) together.
- UI texts live in `frontend/src/i18n` (`en.ts`, `it.ts`): English is the default and the fallback; add every new or
  changed text in Italian too.
- Tests are required: backend in `backend/tests` (pytest, fake driver + mocks, `@pytest.mark.browser` for real
  Chromium), frontend in `frontend/tests` (vitest + Testing Library).
- Attach screenshots (phone width, light and dark) to PRs with visual changes.
- No private data in code, fixtures, logs or screenshots: LAN IPs of your devices, stream URLs with credentials,
  personal playlists, tokens.
- `_old/` is the legacy prototype, kept for reference only: do not change it.
