# Contributing

Use synthetic fixtures and local HTTP/storage. Never commit household accounts/history, device logs,
screenshots, settings exports, backups or third-party patch bundles. Report vulnerabilities through
[private reporting](https://github.com/glasgowm148/kodi-manager/security/advisories/new).

Keep `src/kodi_manager` and `web` canonical. Preserve auth/read-only/profile/version guards; describe
the affected behavior and meaningful validation in PRs. Real TV tests need authorization and known
playback/foreground state; CI must never contact a household TV.

Use a virtual environment with Python 3.9+. Run these checks from the repository root.
The archive globs below use a POSIX shell; in PowerShell, pass the actual archive filenames.
Keep only the current build in `dist/` (move older artifacts elsewhere before building).

```sh
python -m pip install -e '.[dev]'
pytest -q
ruff check .
python -m pip install pyright==1.1.414 && pyright   # types, checked as Python 3.8
node --test tests/*.js
(cd e2e && npm ci && npx playwright test)   # dashboard in Chromium, see e2e/README.md
python -m build
python scripts/build_addon.py
python scripts/test_wheel.py
python scripts/check_release.py dist/*.whl dist/*.tar.gz dist/service.kodi.addonadmin-*.zip --write-checksums dist/SHA256SUMS
```

Bump `src/kodi_manager/version.py` and `addon.xml` together (pyproject reads its version from
`version.py`; the add-on build and `check_release.py` fail on a mismatch), add a changelog entry and
document compatibility. Pushing a `v*` tag runs `.github/workflows/release.yml`, which checks the tag
against `version.py`, rebuilds the ZIP to confirm identical bytes and publishes a prerelease. The
build runs with a read-only token; a separate publish job, the only one allowed to write, runs no
project code: it downloads the built files, checks them against `SHA256SUMS` and creates the release.
Inspect release archives, verify deterministic ZIP bytes and publish `SHA256SUMS`. Keep releases marked
prerelease until the documented live-install/recovery checks pass. Checksums detect changed bytes;
they are not an independent publisher signature. Inspect GitHub CI results before announcing support.

See the [documentation index](docs/README.md) for user and integration guides.
The [Kodi repository publishing guide](docs/repository.md) covers Pages deployment, release
checksums, the repository installer and recovery. No service version bump is needed for docs
or repository infrastructure alone.
