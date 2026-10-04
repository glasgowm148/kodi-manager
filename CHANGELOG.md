# Changelog

## 0.4.1 — 2026-10-04 (prerelease)

- Add-on, stack and pipeline snapshots use unique, exclusively created directories. Backups in the
  same second cannot overwrite one another; restore preserves a separate undo snapshot.
- Restore responses identify `undo_backup_id` or per-add-on `undo_backups`.
- Add clean-wheel installation/recovery smoke checks, archive inspection/checksum tooling,
  dependency/secret checks, compatibility/recovery docs and issue templates.

## 0.4.0 — 2026-10-04 (prerelease)

- Portable Python library, authenticated client, optional Kodi service and dashboard.
- One canonical source produces the library and deterministic companion ZIP.
- Loopback/read-only defaults, masked settings, reviewed Bingie layout gates and synthetic fixtures.

The portable releases omit the original household's credentials, history and third-party patches.
