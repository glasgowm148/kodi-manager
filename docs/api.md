# API and runtime boundaries

All `/api/` endpoints require `Authorization: Bearer TOKEN`, apart from the legacy installer
bootstrap endpoint when installer state exists. The portable release does not create that state.
Successful responses have `{ "ok": true, "data": ... }`; errors have `ok: false` and an error object.
The HTML/JS dashboard is public but its data/actions are authenticated.

| Purpose | Method and endpoint |
|---|---|
| Version, permissions and skin | `GET /api/status` |
| Add-ons and settings | `GET /api/addons`, `GET /api/addons/ID/settings` |
| Pipeline and account evidence | `GET /api/pipeline`, `GET /api/accounts` |
| Settings changes | `PATCH /api/addons/ID/settings`, body `{"changes":[{"id":"SETTING","value":"VALUE"}]}` |
| Sources and current menu/hubs | `GET /api/widgets/sources`, `GET /api/widgets/layout` |
| One provider page | `POST /api/widgets/browse`, body `{"path":"plugin://…","start":0,"limit":24}` |
| A row's contents | `POST /api/widgets/row-preview`, with a saved row/source descriptor |
| Layout preview/apply | `POST /api/widgets/layout/preview`, `POST /api/widgets/layout/apply` |
| Request menu rebuild | `POST /api/widgets/layout/rebuild` |
| Health/logs/backups | `GET /api/health`, `/api/logs`, `/api/kodi/logs`, `/api/backups/timeline` |
| Stack backup/restore | `POST /api/stack/backup`, `POST /api/stack/restore` |

Get the current layout, select a returned section ID, retain `expected_revision` and the existing row
identities/actions, and submit a complete plan to preview. Inspect `can_apply`, `reasons`, exports and
row changes before submitting the **same plan** to apply. Application checks current profile/revision
and writes a backup; the Manager client does not stage/approve the plan for you. nvidia-MCP adds its
own immutable, expiring preview IDs and playback guards around this API.

Service write mode gates mutation endpoints, including install/restore and opening Kodi settings.
Folder, row, layout and dry-run playback previews are read operations, but providers may execute
network requests. Use them in bounded pages with permission to interact with that Kodi setup.
Service settings changes are immediate; write mode does not promise every action is safe during
viewing. Schedule disruptive operations while the TV is free.

The dashboard API returns stored add-on values, including account tokens, unmasked so they can be
entered and repaired from the web UI. Anyone with the bearer token can read them, so keep the token
private and enable LAN access only on a network you trust. The `parse_schema` library function still
masks secret-like values by default. Account/debug/log responses and backups are private diagnostics. Do not send raw diagnostics to an untrusted service. Bearer HTTP has no
encryption; use only a trusted LAN or a user-managed secure tunnel.

These APIs manage installed Kodi functionality. They do not create cloud accounts, migrate Trakt
history, authorize debrid services or install third-party playback/skin patches. Family filters help
with discovery and are not parental access control. Providers supply their metadata and ratings.
