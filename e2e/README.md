# Browser tests

Playwright tests of the dashboard (`web/`) running in Chromium against `scripts/demo_server.py`:
synthetic data only, never a TV. Each worker starts its own demo server on a free port with the clock
frozen at `2026-10-11T12:00:00` UTC (`--now`, `TZ=UTC`), and the browser clock is frozen to the same
instant, so pages and screenshots are identical on every run.

| File | What it checks |
| --- | --- |
| `tests/dashboard.spec.js` | Sign-in, Overview (verdict and tiles), side menu (desktop) and bottom bar with More (phone), Trends charts, Row health filters/search/sort, saving a setting, the `playback_active` refusal, a view-only profile, the Backups restore dialog, the theme button |
| `tests/layout.spec.js` | No page scrolls sideways at 390 px (phone project) |
| `tests/screenshots.spec.js` | Overview, Trends, Row health and Backups against stored screenshots, desktop (1280×800) and phone (390×844) |

Every test also fails on a browser console error or an uncaught exception.

## Run

Needs Node 20+, Python 3.8+ (`python3`, or set `PYTHON`) and Playwright's Chromium.

```sh
cd e2e
npm ci
npx playwright install chromium   # skip if Chromium for Playwright 1.63 (chromium-1243) is already installed
npx playwright test
npx playwright show-report        # after a failure
```

## Screenshot baselines

Baselines live in `tests/__screenshots__/`, one per page, project and platform
(`overview-desktop-darwin.png`, `overview-phone-linux.png`, …): fonts differ between macOS and Linux.
A screenshot test **skips** while its baseline is missing, so a fresh checkout and CI stay green until
baselines are committed. Write or refresh them, check the images, then commit them:

```sh
npx playwright test --update-snapshots
git add tests/__screenshots__
```

To compare in CI (ubuntu-latest) as well, generate the Linux baselines in Playwright's image:

```sh
docker run --rm -v "$(cd .. && pwd)":/work -w /work/e2e mcr.microsoft.com/playwright:v1.63.0-noble \
  bash -c "apt-get update -qq && apt-get install -y -qq python3 >/dev/null && npm ci && npx playwright test --update-snapshots"
```

The comparison tolerates anti-aliasing (`threshold: 0.2`) and at most 1 % of differing pixels.
