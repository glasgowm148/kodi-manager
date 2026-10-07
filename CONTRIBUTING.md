# Contributing

Use synthetic fixtures and local HTTP/storage. Never commit household accounts/history, device logs,
screenshots, settings exports, backups or third-party patch bundles. Report vulnerabilities through
[private reporting](https://github.com/glasgowm148/kodi-manager/security/advisories/new).

Keep `src/kodi_manager` and `web` canonical. Preserve auth/read-only/profile/version guards; describe
the affected behavior and meaningful validation in PRs. Real TV tests need authorization and known
playback/foreground state; CI must never contact a household TV.

```sh
python -m pip install -e '.[dev]'
pytest -q
ruff check .
node --test tests/*.js
python -m build
python scripts/build_addon.py
python scripts/test_wheel.py
python scripts/check_release.py dist/*.whl dist/*.tar.gz dist/service.kodi.addonadmin-*.zip --write-checksums dist/SHA256SUMS
```

Bump `src/kodi_manager/version.py` and `addon.xml` together (pyproject reads its version from
`version.py`; the add-on build and `check_release.py` fail on a mismatch), add a changelog entry and
document compatibility. Pushing a `v*` tag runs `.github/workflows/release.yml`, which checks the tag
against `version.py`, rebuilds the ZIP to confirm identical bytes and publishes a prerelease.
Inspect release archives, verify deterministic ZIP bytes and publish `SHA256SUMS`. Keep releases marked
prerelease until the documented live-install/recovery checks pass. Checksums detect changed bytes;
they are not an independent publisher signature. Inspect GitHub CI results before announcing support.
