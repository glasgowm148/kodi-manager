# Browser tests

Playwright tests of the dashboard (`web/`) running in Chromium against `scripts/demo_server.py`:
synthetic data only, never a TV. Each worker starts its own demo server on a free port with the clock
frozen at `2026-10-11T12:00:00` UTC (`--now`, `TZ=UTC`), and the browser clock is frozen to the same
instant, so pages and screenshots are identical on every run.

| File | What it checks |
| --- | --- |
| `tests/dashboard.spec.js` | Sign-in, Overview (attention, tasks, logs and device cards), side menu (desktop) and bottom bar with More (phone), Trends charts, Row health filters/search/sort, saving a setting, the `playback_active` refusal, a view-only profile, the Backups restore dialog, the theme button |
| `tests/layout.spec.js` | No page scrolls sideways at 390 px (phone project) |
| `tests/screenshots.spec.js` | Overview, Health, Trends, Row health and Backups against stored screenshots, desktop (1280×800) and phone (390×844) |

Every test also fails on a browser console error or an uncaught exception.

## Run

Needs Node 20+, Python 3.8+ (`python3` on macOS/Linux, `python` on Windows, or set `PYTHON`) and Playwright's Chromium.

```sh
cd e2e
npm ci
npx playwright install chromium   # installs the version pinned by package-lock.json
npx playwright test
npx playwright show-report        # after a failure
```

## Screenshot baselines

Baselines live in `tests/__screenshots__/`, one per page, project and platform
(`overview-desktop-darwin.png`, `overview-phone-linux.png`, …): fonts differ between macOS and Linux.
A screenshot test **skips** while its platform baseline is missing; a green run with skips does
not verify appearance on that platform. Behavioral tests still run. Write or refresh them, check the images, then commit them:

```sh
npx playwright test --update-snapshots
git add tests/__screenshots__
```

The Linux baselines CI compares against are written by CI itself, so fonts and Chromium match
exactly: run the **Test and package** workflow by hand with `update_snapshots` ticked, download its
`linux-screenshots` artifact and commit the `*-linux.png` files:

```sh
gh workflow run ci.yml --repo glasgowm148/kodi-manager -f update_snapshots=true
gh run download <run-id> --repo glasgowm148/kodi-manager -n linux-screenshots -D tests/__screenshots__
git add tests/__screenshots__/*/*-linux.png
```

The comparison tolerates anti-aliasing (`threshold: 0.2`) and at most 1 % of differing pixels.

See [Contributing](../CONTRIBUTING.md) for the full checks and [documentation](../docs/README.md) for user guides.
