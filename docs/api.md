# HTTP API

The dashboard is a static page plus this JSON API, served by the Kodi Manager service inside Kodi
(default port 8765). This list follows `route_api` in `src/kodi_manager/server.py`.

## Conventions

- **Auth.** Every `/api/` request needs `Authorization: Bearer TOKEN`. The only exception is
  `GET /api/bootstrap/status`, and only while legacy installer files exist (the portable release never
  creates them). A missing or wrong token answers `401` with code `unauthorized`. When **Allow LAN
  access** is on, requests from non-private addresses are refused with `403` `forbidden`.
- **Envelope.** Success: `{"ok": true, "data": …}`. Failure: `{"ok": false, "error": {"code": "…",
  "message": "…", "details": {…}}}`. Clients should branch on `code`, not on the message text.
- **Writes.** Every `POST` or `PATCH` needs **Enable writes** turned on in the add-on settings, except
  the read-only posts marked *read* below. With writes off they answer `403` `write_disabled`.
  A write that changes settings makes a backup first.
- **Busy Kodi.** Actions that would interrupt viewing (install dialog, fix repair, menu rebuild) refuse
  while something is playing. Restores answer `409` when Kodi is busy; resend the same body with
  `"force": true` to restore anyway.
- Bodies are JSON objects of at most 1 MB. `ID` is a Kodi add-on id, URL-encoded.

## Status and discovery

| Method and path | Writes | Request | Response `data` |
|---|---|---|---|
| `GET /api/status` | – | – | `service_version`, `Kodi version`, `server` `{host, port}`, `write_enabled`, `allow_lan`, `active_skin`, `current_time`, `platform`, `stack` (detected skin, helpers, players, `warnings`) |
| `GET /api/bootstrap/status` | – | – | `{installed, web_url, needs_auth, nonce_present}` (legacy installer only) |
| `GET /api/stack` | – | – | Detected stack: `skin` (with `bingie_like`), `tmdbhelper`, `fenlight`, `fen`, `pov`, `cocoscrapers`, `trakt`, `trakt_integration`, `warnings`, … |
| `GET /api/health` | – | – | `{status, checks[], stats{}, recent_errors[], recent_warnings[]}` |
| `GET /api/integrations` | – | – | Account-integration summary per add-on |
| `GET /api/addons` | – | – | Array of add-ons: `addon_id`, `name`, `version`, `installed`, `enabled`, `config_present`, … |
| `GET /api/addons/ID` | – | – | That add-on plus `warnings[]` and `related` details |
| `GET /api/search/config?q=TEXT` | – | – | `{query, count, results[]}`; each result has `addon_id`, `addon_name`, `group`, `id`, `label`, `value`, `type`, `editable`, `masked`, `warning` (at most 500) |
| `GET /api/logs` | – | – | `{lines[]}`: the service's last 200 log lines |
| `GET /api/kodi/logs` | – | – | `{lines[]}`: the last 500 lines of Kodi's log |
| `GET /api/debug/paths` | – | – | Kodi version, platform and resolved profile paths |
| `GET /api/debug/stack-raw` | – | – | Raw add-on probes, merged records and the classified stack |

## Add-on settings and backups

| Method and path | Writes | Request | Response `data` |
|---|---|---|---|
| `GET /api/addons/ID/settings` | – | – | `{addon_id, name, adapter, groups[{label, settings[]}], warnings[], editable, read_only_reason}`. Each setting has `id`, `label`, `type`, `value`, `default`, `options`, `editable`, `masked`, `description`, `warning`. When `editable` is `false`, show the settings read-only with `read_only_reason`. |
| `PATCH /api/addons/ID/settings` | yes | `{"changes": [{"id": "SETTING", "value": "VALUE", "source": "settings.xml"}]}`; `source` may be `settings.db` (Fen Light) or `raw` | `{changed_count, backup_id, warnings[]}`. `403 addon_not_allowed` for add-ons outside the detected stack unless listed in **Also allow editing these add-ons**. |
| `POST /api/addons/ID/backup` | yes | `{}` | Backup manifest: `{backup_id, addon_id, addon_name, addon_version, timestamp, files_copied, …}` |
| `GET /api/addons/ID/backups` | – | – | `{backups[]}`: that add-on's manifests, newest first |
| `POST /api/addons/ID/restore` | yes | `{"backup_id": "…", "force": false}` | `{restored: true, backup_id, undo_backup_id, restart_required}`. Restore `undo_backup_id` to undo. |
| `POST /api/addons/ID/open-settings` | yes | `{}` | `{opened}`: opens the add-on's own settings dialog on the TV |
| `POST /api/stack/backup` | yes | `{}` | Checkpoint manifest: `{backup_id, timestamp, included_folders[], skipped_folders[], …}` covering the skin, helpers and players |
| `GET /api/stack/backups` | – | – | `{backups[]}`: checkpoint manifests |
| `GET /api/backups/timeline` | – | – | `{items[], count}`: checkpoints and playback-setting backups, newest first, each with `kind`, `component_count`, `skipped_count` |
| `POST /api/stack/restore` | yes | `{"backup_id": "…", "force": false}` | `{restored[], skipped[], undo_backups{ADDON_ID: BACKUP_ID}, restart_required}`. Restore each undo backup with `POST /api/addons/ID/restore` to undo. |

Backups live in the Kodi profile under `addon_data/service.kodi.addonadmin/backups`. See
[recovery](recovery.md) for retention and restoring by hand.

## Playback setup and accounts

| Method and path | Writes | Request | Response `data` |
|---|---|---|---|
| `GET /api/pipeline` | – | – | `{nodes[], edges[], routing{}, summary{primary_player, secondary_players, scraper_module, helper, health, accounts}, settings_groups[], discovery}` |
| `GET /api/pipeline/debug` | – | – | `{pipeline, paths, stack_raw}` |
| `POST /api/pipeline/rescan` | read | `{}` | Same as `GET /api/pipeline` after re-reading add-ons |
| `POST /api/pipeline/backup` | yes | `{}` | Manifest `{backup_id, included_components[], skipped_components[], …}` |
| `PATCH /api/pipeline/settings` | yes | `{"changes": [{"component", "setting_id", "source", "value"}]}` | `{backup_id, changed_count, changed_settings[], warnings[], restart_recommended}`; `400 invalid_pipeline_setting` for anything outside the routing controls |
| `POST /api/pipeline/switch-player` | yes | `{"target_player_addon_id", "apply_to", "keep_current_as_fallback": true}` | `{supported, backup_id, reason, …}`; `400 switch_player_blocked` when routing is player-file based |
| `POST /api/playback/test` | read | `{"target_player_addon_id", "plugin_url"}` | Dry run: `{ok, dry_run: true, target_player_addon_id, steps[{step, ok, detail}], pipeline_routing}`. Never starts playback. |
| `GET /api/accounts` | – | – | `{groups[], summary{trakt, torbox, tmdb, debrid}, notes[]}` |
| `PATCH /api/accounts/settings` | yes | `{"changes": [{"component", "setting_id", "source", "value"}]}` | `{backup_id, changed_count, changed_settings[], …}`; `400 account_write_blocked` |
| `POST /api/trakt/sync` | yes | `{}` | Runs `script.trakt` sync; `404 trakt_unavailable` if it is not installed and enabled |

## Kodi actions

| Method and path | Writes | Request | Response `data` |
|---|---|---|---|
| `POST /api/addons/install` | yes | `{}` | `{opened, next_step}` or `{opened: false, error}`. Opens Kodi's own **Install from zip file** dialog on the TV; Kodi has no API to install a ZIP from a path. Refused while playing. |
| `POST /api/windows/open-skin-settings` | yes | `{}` | `{opened}` |
| `GET /api/fixes` | – | – | `{healthy, bundled, repairable, detail, groups[{label, status, installed_version, tested_version}]}` |
| `POST /api/fixes/repair` | yes | `{}` | `{detail, …}`. Backs up, then restores tested copies of known files. Refused while playing. |

## Home layout (supported skins)

The layout editor works on skins Kodi Manager can read safely (`stack.skin.bingie_like` today).
Other skins report read-only sections with `reasons`.

| Method and path | Writes | Request | Response `data` |
|---|---|---|---|
| `GET /api/widgets/sources` | – | – | `{sources[{addon_id, label, path, enabled, traversable}]}` |
| `GET /api/widgets/layout` | – | – | `{revision, sections[], inactive_sections[], menu_entries[], max_rows, can_apply, new_section, reasons[]}` |
| `POST /api/widgets/browse` | read | `{"path": "plugin://…", "start": 0, "limit": 48, "refresh": false, "family_preview": false, "max_rating": "12A"}` | One page of a folder: `{items[], children[], skips[], classification, can_use_as_widget, …}` plus `family_preview` when asked |
| `POST /api/widgets/suggestions` | read | `{}` | Suggested family rows |
| `POST /api/widgets/row-preview` | read | `{"section_id", "row_id", "limit"}` | Titles a saved row shows today |
| `POST /api/widgets/layout/preview` | read | Plan: `{"section_id", "label", "rows": [{"id"?, "label", "path", "action"?}], "expected_revision"}` | The resulting layout with `can_apply` and `reasons` |
| `POST /api/widgets/layout/apply` | yes | The same plan | `{applied, backup_id, changed_files, …}` after re-checking the profile and revision |
| `POST /api/widgets/layout/rebuild` | yes | `{}` | `{started}`: asks the skin to rebuild its menu. Refused while playing. |

Get the layout, pick a section, keep `expected_revision` and the existing row ids and actions, preview
the complete plan, check `can_apply` and `reasons`, then apply **the same plan**.

## Cached rows (optional widget cache)

| Method and path | Writes | Request | Response `data` |
|---|---|---|---|
| `GET /api/widget-cache` | – | – | `{root, entries[{source, items, age_seconds, stale, progress}], queued}` |
| `POST /api/widget-cache/refresh` | read | `{}` | `{queued}`: number of cached sources queued for refresh |
| `GET /api/widget-cache/url?source=plugin://…&pages=2&hide_watched=true` | – | – | `{url}`: the cached URL to give a skin widget; `400 bad_request` for an unsupported source |
| `GET /api/widget-cache/rows` | – | – | Array of rows `{id, label, source, pages, hide_watched, widget_url}` |
| `POST /api/widget-cache/rows` | yes | `{"label", "source", "pages", "hide_watched"}` | The saved row. Saving an existing source updates it. |
| `POST /api/widget-cache/rows/remove` | yes | `{"id"}` | `{removed: true}` |

See [widget cache](widget-cache.md) for how skins use these rows.

## Boundaries

Changes to Kodi Manager's own settings (Allow LAN access, Enable writes, port and so on) apply while
it runs; no Kodi restart is needed. Enable writes does not make every action safe during viewing:
schedule disruptive operations while the TV is free.

Folder, row, layout and dry-run playback previews are read operations, but they run the installed
add-ons' own code, which may make network requests. Use them in bounded pages.

The API returns stored add-on values, including account tokens, unmasked so they can be entered and
repaired from the dashboard. Anyone with the bearer token can read them: keep the token private and
turn on LAN access only on a network you trust. The `parse_schema` library function still masks
secret-like values by default. Account, debug and log responses and backups are private diagnostics;
do not send them to an untrusted service. The API is plain HTTP with no encryption: use it only on a
trusted LAN or through a secure tunnel you manage.

These APIs manage installed Kodi functionality. They do not create cloud accounts, migrate Trakt
history, authorize debrid services or install third-party playback or skin patches. Family filters
help with discovery and are not parental access control.

### Protected settings (0.7.3)

| Method and path | Access | Body | Result |
| --- | --- | --- | --- |
| `GET /api/baseline` | read | – | `{items[{key, kind, label, expected, current, ok, missing}], count, drifted}` |
| `POST /api/baseline/capture` | write | `{"items": [{"kind": "addon_setting", "addon", "id", "label"?, "value"?} \| {"kind": "kodi_setting", "id", ...} \| {"kind": "addon_xml", "addon", "tag", ...}]}` | Protects each item at its current (or given) value: `{protected[], count}` |
| `POST /api/baseline/apply` | write | `{"keys"?: [...]}` | Re-applies drifted items: `{applied[], failed[], restart_required}` |
| `POST /api/baseline/remove` | write | `{"keys": [...]}` | `{count}` |

Health also lists **Protected settings**, **Trakt sign-in**, **TorBox subscription**, **Nightly
checkpoint**, **Internet (add-on services)** and **Memory**; a check may carry
`action: {label, path}` that the dashboard offers as a button.
