# Changelog

## 0.4.2 — 2026-10-06 (prerelease)

- The installer seed is applied once. LAN access, host and port changes made later in the add-on
  settings now persist across restarts, and `installer_result.json` (which holds the token) is no
  longer rewritten on every start.
- Backups honour **Backup retention** (default 20 per add-on, stack and pipeline). Kodi Manager's
  own snapshots no longer copy its backup store into themselves. Switching player no longer takes
  a full snapshot when nothing changes.
- Restore now replaces the folder contents: files created after the snapshot are removed.
  Stack restore works for add-ons whose data path was not detected.
- Install from ZIP opens Kodi's own Install from zip file dialog on the TV. Kodi's `InstallAddon`
  builtin only accepts add-on IDs, so the old path-based request never installed anything.
- Menu rebuild and opening Install from zip refuse to run while something is playing.
- Fix-protection backups made in the same second no longer collide.
- A non-ASCII Authorization header is rejected with 401 instead of dropping the connection.
- Removed the unused **Allow secret replacement** setting. The dashboard shows account tokens so
  they can be entered and repaired; the docs now say so.

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
