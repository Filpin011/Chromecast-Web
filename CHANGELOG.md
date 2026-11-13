# Changelog

Maintained by [release-please](https://github.com/googleapis/release-please) from
[Conventional Commits](https://www.conventionalcommits.org/); versions follow [SemVer](https://semver.org/).

## 0.1.0 (2026-11-13)


### ⚠ BREAKING CHANGES

* rewrite as FastAPI backend + Next.js frontend

### Features

* **brand:** brand wallpaper for the TV idle image and README banners ([2e93cd5](https://github.com/Filpin011/Chromecast-Web/commit/2e93cd5499350afb9822d9e8552d877b11b9016a))
* **i18n:** English by default with full Italian localisation ([ff9fc31](https://github.com/Filpin011/Chromecast-Web/commit/ff9fc31266343c56c53bc3ca3213249ed8ab1b51))
* local "Watch here" player, remote-browser fixes and brand wallpaper ([9cada57](https://github.com/Filpin011/Chromecast-Web/commit/9cada5794bafef66afe217d667d8e517ede60f23))
* **player:** local "Watch here" player with HLS/DASH, TV hand-off and full screen ([a1f6a68](https://github.com/Filpin011/Chromecast-Web/commit/a1f6a681663cd4a53dcff63f6c81a7d9e9a11009))
* rewrite as FastAPI backend + Next.js frontend ([c139066](https://github.com/Filpin011/Chromecast-Web/commit/c1390667db792a957413332105280e6d22da9aad))


### Bug Fixes

* **browser:** don't capture disguised HLS segments as separate streams ([83cb9a1](https://github.com/Filpin011/Chromecast-Web/commit/83cb9a12e81593012162fd67fdfa384ce6db3712))
* **browser:** neutralise anti-devtools console probes in the remote browser ([f6534cf](https://github.com/Filpin011/Chromecast-Web/commit/f6534cf92f992b6aa5a0c6b24a1c0f27667afd45))
* **docker:** install libatomic1 needed by Playwright's bundled Node ([c159841](https://github.com/Filpin011/Chromecast-Web/commit/c1598417bded2236580ae9f6367d1750842b43a4))
* harden casting, proxy, browser and UI after review rounds ([37763f1](https://github.com/Filpin011/Chromecast-Web/commit/37763f1cca99fd283609dafb8cbc36ba2129a7d7))

## 0.0.0 (prototype, never released)

- Original Python prototype, kept read-only in `_old/` for reference. Release-please writes the notes of
  every real release (starting with 0.1.0, the FastAPI + Next.js rewrite) above this entry.
