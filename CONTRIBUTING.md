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
python scripts/check_release.py dist/kodi_manager-0.4.1-py3-none-any.whl dist/kodi_manager-0.4.1.tar.gz dist/service.kodi.addonadmin-0.4.1.zip --write-checksums dist/SHA256SUMS
```

Update library/add-on/pyproject versions together, add a changelog entry and document compatibility.
Inspect release archives, verify deterministic ZIP bytes and publish `SHA256SUMS`. Keep releases marked
prerelease until the documented live-install/recovery checks pass. Checksums detect changed bytes;
they are not an independent publisher signature. Inspect GitHub CI results before announcing support.
