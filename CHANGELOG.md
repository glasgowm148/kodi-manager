# Changelog

## 0.7.34 — 2026-10-13

- Check cancellation during backup traversal and between 1 MiB copy chunks. A large cache file no longer holds nightly maintenance through a profile switch; cancelled snapshots are discarded and an existing destination remains intact.
- Include the active watchdog phase in pending-worker diagnostics to distinguish maintenance from connection checks and metrics.

## 0.7.33 — 2026-10-13

- Stop dashboard producers and retire the listener before private extension cleanup, so cleanup waits cannot leave those producers starting more Kodi work during shutdown.
- Cancel a saturated HTTP handler-slot wait when the dashboard retires; the listener no longer stays alive for the five-second admission timeout during profile changes.
- Stop widget refresh results and health callbacks from making new native Kodi calls after shutdown begins; retain the previous cached row when a listing is cancelled.
- Record pending profile-drain worker names before waiting: Kodi may terminate an aborted script before the drain timeout finishes. No Python frame inspection or credentials are recorded.

## 0.7.32 - 2026-10-13 (prerelease)

- Recognize Bingie 2.0.2.6's unchanged focus-control diagnostic as a known notice, as for the reviewed 2.0.2.3/2.0.2.5 versions. Other controls, unknown skin versions and real errors still warn. Original log entries remain intact.
- Clarify first-run setup, the home-screen menu versus My add-ons, and setting a private Auth token through Configure when the token-display menu is inaccessible.

## 0.7.31 — 2026-10-13 (prerelease)

- Restore the clickable chart cards to the top of Overview, with management shortcuts below. Unchecked services stay on their cards without a redundant attention alarm.
- Show retained log totals alongside counts since this Manager version began recording and the last warning/error time. Historical errors are labelled as recorded events, not current faults; collection failures remain explicit.
- Mask IPTV stream-path credentials in new logs and older retained responses.
- Keep original log entries, review state, auth and write guards intact. Fix spacing in the view-only banner.

## 0.7.30 — 2026-10-13 (prerelease)

- Rework Overview around prioritised problems, direct management tasks, recent log activity and device details. Replace the decorative TV graphic with a compact profile/playback summary.
- Collapse navigation into task groups while preserving all routes, add-on shortcuts, mobile navigation and keyboard focus across refreshes. Keep read-only guidance compact and update access state on refresh.
- Separate current Health faults from retained 24-hour logs; keep passed checks and detailed figures in expandable sections. Treat read-only mode and optional add-on choices as information, not faults.
- Preserve existing authentication, write/playback guards, history, settings and backup flows.

## 0.7.29 — 2026-10-13 (prerelease)

- Group retained diagnostics by cause, with recorded-entry counts, first/last seen, source evidence and suggested next steps. Keep every original event and its pagination available.
- Record per-issue review points when writes are enabled; later events show recurrence without clearing counts. Automatic comparison points record when each Manager version first starts collecting.
- Migrate older retained entries in bounded batches. Issue groups have level filters, pagination and links to their original entries; Health shows a concise issue overview.

## 0.7.28 — 2026-10-12 (prerelease)

- Mask signed BBC/Akamai, CloudFront and cloud-storage URL credentials in log diagnostics.
  Retained entries from older versions also receive the current masking rules when read;
  warning/error counts, IDs and the original history tracking start are preserved.

## 0.7.27 — 2026-10-12 (prerelease)

This release includes the changes since 0.7.23: clearer add-on purposes/dependencies
and removal guidance, persistent masked 24-hour log history with filters, metadata
normalization and service shutdown fixes. Upgrade using the installable add-on ZIP;
the wheel is the separate Python client library. Historical warnings remain until
their 24-hour expiry. Household provider patches are not included.

- Preserve the original Monitor's abort signal when shutdown begins during service
  startup. A callback monitor registered later can miss Kodi's earlier notification;
  the service now exits instead of waiting for Kodi to kill it after five seconds.

## 0.7.26 — 2026-10-12

- Skip absent video metadata and normalize missing cast strings before calling Kodi's
  native APIs, which warn when passed `None`. Keep zero values and valid metadata.
- Avoid retaining native player/window objects in the widget refresher across shutdown.
- Recognize the unchanged intentional focus controls in Bingie 2.0.2.5 as known notices.
  Retained history still includes every original warning; previous entries expire normally.

## 0.7.25 — 2026-10-12

- Health counts warnings, errors and known notices over the past 24 hours. A background
  collector imports the available current/previous logs and then reads new bytes, even
  while playing. Masked history persists across restarts and profile changes; old entries expire.
- Kodi log opens the retained history with level filters and pages of older entries.
  The current 500-line raw tail remains available separately. Collection failures and
  initial catch-up are shown instead of claiming the log is clear.

## 0.7.24 — 2026-10-12 (prerelease)

- Explain add-on purposes, Kodi components, shared libraries, update repositories, resource packs and background services. Link declared dependents, including disabled and optional imports; add type/review filters and conservative removal guidance for the current profile. Repeat explanations on settings pages. No automatic removal or device mutations are added.
- Prefer updated user-installed manifests over bundled copies, so versions and dependency relationships remain accurate.

- Clarify clean Python-library installation, checksum verification, current Connection navigation, token storage/authentication and storage-blocked sign-in. Correct provider-cache and add-on editing support claims.
- Shorten the main README and add linked documentation indexes, FAQ and Python library examples. Clarify add-on editing limits, background activity and screenshot-test skips; runtime is unchanged.

- Give the oversized virtual-write fixture a short test ID instead of embedding its two-megabyte buffer in CI output. Bound test processes and console lines, retain full logs as artifacts, and cancel superseded runs. These changes affect tests and CI; add-on runtime bytes are unchanged.

## 0.7.23 — 2026-10-12 (prerelease)

- Recheck bearer authorization, write mode, service retirement and active profile after receiving action bodies. Stopped service generations refuse queued actions; profile changes during reads suppress their results. Errors require reconnecting and inspecting before retrying.
- Pin backup roots to configured service generations and per operation/thread, including nested undo creation, rollback and retention. A profile switch cannot redirect pruning or make rollback look in another profile. Cover add-on, selected-file, stack and pipeline snapshots.
- Preserve distinct native XML edits/deletions detected during failed write readback; unreadable ownership refuses blind rollback. Retain the backup for explicit recovery.
- Map canonical tvOS userdata paths back to Kodi's translated VFS keys, including layout reads/writes/listing/deletion. Canonical and alias paths share write locks; physical shadows cannot replace actual XML preferences.
- Add delayed-body access/profile regressions, cross-profile read/lookup refusal, canonical layout storage and six backup-root transition cases. Preserve live access settings, VFS aliases and existing layout gates. No live TV changes.

## 0.7.22 — 2026-10-12 (prerelease)

- Preserve live Manager access settings and device identity during failed add-on/checkpoint restore rollback, just as during successful restore. A token changed after the undo snapshot must not be resurrected from that snapshot.
- Preserve translated backup-root spelling for tvOS VFS keys while resolving canonical paths for confinement checks. Directory aliases no longer send XML snapshots to physical shadows. Existing traversal/symlink refusal remains.
- Test failed self-restore on POSIX and virtual storage, aliased backup/restore/undo and missing virtual backup keys. Older alias-affected physical snapshots may be refused as incomplete; take a fresh validated snapshot and retain independent private recovery copies. No live TV changes or physical Apple TV validation.

## 0.7.21 — 2026-10-12 (prerelease)

- Preserve Kodi's translated path spelling when reading virtual `profiles.xml`; resolve canonical paths only for confinement comparisons. An alias such as `/var` → `/private/var` must not bypass the nested-profile check. Add a synthetic directory-alias regression.
- Retain 0.7.20's nested-profile and physical Siri Remote XML fixes. Prefer this release over 0.7.20 for tvOS profile reads.

## 0.7.20 — 2026-10-12 (prerelease)

- Confine portable file reads when a configured profile is nested inside the active profile. Allow the active nested profile itself while refusing parent/sibling configuration.
- Match Kodi's tvOS storage exception for `customcontroller.SiriRemote*.xml`: read, atomically replace, back up and delete these physical files without using virtual preference keys.
- Add synthetic nested-profile and Siri Remote storage regressions. No physical Apple TV validation or household TV changes.

## 0.7.19 — 2026-10-12 (prerelease)

- Bound portable path-parent traversal and recognize Windows short-path/case aliases. An unmatched root cannot loop forever; symlink checks still inspect every yielded path. Resolve nonstandard profile directories against the canonical master path; reject case aliases of other profiles on case-insensitive storage.
- Add Windows-path alias/missing-boundary regressions, CI stack dumps for stalled tests and a bounded job duration. Keep the 0.7.17/0.7.18 VFS and ownership safeguards.

## 0.7.18 — 2026-10-12 (prerelease)

- Check virtual existence/stat as well as handle length: Kodi's Python File constructor ignores failed native opens, which can otherwise look like a successful zero-byte read. Refuse missing/disappearing files and preserve the original on open failure.
- Add synthetic failed-open/missing-key regressions; retain the ownership and backup safeguards from 0.7.17. No live TV changes or physical Apple TV validation.

## 0.7.17 — 2026-10-12 (prerelease)

- Check virtual file length before/after reading: Kodi can return partial data without an exception. Refuse empty/oversized virtual writes before mutation and retain the old value.
- Refuse a missing tvOS source directory instead of creating an empty snapshot of inaccessible persistent XML. Cache purging still requires independent private recovery.
- Bind portable file responses to device/profile ownership, accept expected ownership in queries, pin the absolute profile path and reject configured nonstandard profiles from master-profile reads.
- Keep live Manager identity/access files untouched throughout self-restore, including concurrent reads. Preserve existing Android behavior and reviewed skin gates.

## 0.7.16 — 2026-10-12 (prerelease)

- Add experimental Apple TV handling for userdata XML stored in Kodi VFS/NSUserDefaults.
  Read the virtual value, write it once, verify readback and roll back on failure. Layout edits,
  add-on/checkpoint/pipeline backups, restore, undo and pruning use that storage explicitly.
  Other platforms retain POSIX atomic writes; no global filesystem monkeypatching.
- Add authenticated portable state and bounded active-profile/add-on text reads for clients
  without ADB. Persist a Manager-instance identity, preserve it on self-restore, and reject
  other profiles, traversal, symlinks and oversized reads.
- Read native tvOS application state without UI actions. Inactive/unknown focus blocks action
  requests, even body-free handlers and forced restores; checkpoint work stops if focus is lost.
  Existing read-only/token defaults and layout source/version/revision gates remain.
- Document experimental tvOS setup, disposable cache/backup-manifest limits and unavailable
  Android recovery. No physical Apple TV validation or household TV changes performed.

## 0.7.15 — 2026-10-12 (prerelease)

- Reject short, malformed or slowly streamed request bodies before any action, including handlers
  that take no body fields. Enforce a 20-second total body deadline so dripping clients cannot
  retain handler slots indefinitely; handle client disconnects without traceback noise.
- Preflight every declared checkpoint folder before restoring. Missing components and corrupt
  metadata cannot trigger partial restores; undeclared extra folders are ignored. Legacy snapshots
  without metadata retain their existing checks.
- Normalize malformed/truncated HTTP responses into library `ManagerError` failures. Restrict
  error codes and redact the configured bearer token from upstream error messages.

## 0.7.14 — 2026-10-12 (prerelease)

- Explain Android TV / Google TV / Fire OS installation, optional ADB, separate pairing ports,
  restricted storage and small-device cache limits; distinguish Vega OS Firesticks.
- Network notifications use device-neutral advice. Add regression coverage that the opt-in
  NVIDIA exit workaround stays disabled on other Android devices.

## 0.7.13 — 2026-10-12 (prerelease)

- Dashboard requests time out after 60 seconds, including a stalled response body, and release
  busy controls. No change is retried automatically: a timeout can mean Kodi is still working.
- A delayed authentication failure from an old token no longer clears a newer sign-in. This can
  happen when signing in again after a Kodi profile change while an earlier request is pending.
- Setup now identifies the installable release asset, profile-specific tokens, HTTP versus HTTPS,
  manual updates, skin support, cached-row setup and common network failures. The README and
  compatibility page distinguish the public package from live use with household extensions.
- Includes 0.7.12's corrected log-level and known-notice handling, previously on main only.

## 0.7.12 — 2026-10-12 (prerelease)

- **Log health follows log levels.** Words such as "error" inside an INFO message no longer
  raise an alert. A settings schema warning followed by its JSON-RPC resolution, and the
  reviewed focus-button compatibility notice on active Bingie 2.0.2.3, are reported as known
  notices. Other warnings, unresolved schema warnings, unknown skin/control versions and real
  errors still alert. Raw warning lines remain available in diagnostics.

## 0.7.11 — 2026-10-11 (prerelease)

- **Only real listings run from the dashboard.** Browsing, row previews, family rows and cached rows
  now check POV, Fen, Fen Light, TMDb Helper (both add-on IDs), BBC iPlayer, Bingie Widgets and Kodi
  Manager's own rows against an explicit list of each add-on's listing routes, taken from their
  routers (`KNOWN_ROUTES` in `route_guard.py`), instead of guessing from words in the URL. Anything
  else they route to is refused, as are path-based routes and a repeated `mode=`; a cached or family
  row's own source is checked too. Other add-ons keep the word check. Checked against 9,383 plugin
  URLs seen on one TV:
  - BBC iPlayer play items (`mode=201`–`205`), sign-out, search, red-button and "mark watched" routes
    were accepted before and are now refused.
  - TMDb Helper's "Now playing" lists and BBC iPlayer programmes whose address or description
    contains "play" (*Play School*) were refused before and now work.
  - POV routes that do not exist in POV (`mode=trakt_lists`, `mode=navigator`) are refused.
- **A skin menu item without its `<label>` or `<action>`** now refuses a layout edit with a clear
  message (400) instead of failing with a server error.
- **All add-ons fits a phone.** The page was wider than the screen on phones (the table's hidden
  "Actions" heading escaped its scroll box), so the whole page zoomed out; wide tables now scroll
  inside their own box everywhere.

### For developers

- **Smaller modules.** `server.py` is split into `http_base.py` (request checks, envelope, bounded
  server), `api_status.py`, `api_addons.py` and `api_widgets.py` (handlers by area) and
  `dashboard_data.py`; `service.py` into `service_config.py` and `service_workers.py`; the
  service-side `Refresher` moves from `widget_cache.py` to `widget_refresher.py`. Every name that was
  importable from `server`, `service` and `widget_cache` still is, and the HTTP API is unchanged
  (all 69 requests of a smoke run answer identically). Tests patch names where they are looked up.
- **Type checking.** pyright 1.1.414 checks `src/` as Python 3.8 in CI, with stubs for Kodi's modules
  in `typings/`; the errors it found were fixed in the code.
- **Browser tests.** `e2e/` runs the dashboard in Chromium (Playwright 1.63.0) against the demo
  server: navigation on desktop and phone, Trends, Row health, saving a setting, refusals, the theme,
  no sideways scrolling at 390 px and screenshots of four pages. `scripts/demo_server.py --now`
  freezes the demo clock.

## 0.7.10 — 2026-10-11 (prerelease)

- **A stalled exit on the Shield really ends after a minute.** Quitting Kodi 22.0 RC1 could still
  hang after "Stopping all" for minutes and need a force-stop. The watcher was running (it is
  launched when Kodi announces the quit, `Shield exit guard armed on quit`), but it counted its
  60 seconds as 3000 polls of 20 ms, and on a Shield each poll starts two toybox processes and takes
  0.1–0.2 s, so the limit was five minutes or more. It now also measures the time since "Stopping
  all" on the boot clock (`/proc/uptime`, or mksh's `SECONDS` where that is unreadable) and ends
  the exit once more than 60 seconds have passed; the 3000-poll limit stays as a fallback. The
  conditions are unchanged: "Stopping the application", "Saving skin settings" and "Stopping all"
  in that order in this session's log, and the same process (parent and start tick) as when armed.
- **The watcher stops when Kodi is not quitting.** Without "Stopping all" it gives up after
  120 seconds on the clock as well as after 1500 polls, and playback starting after the quit
  sequence (`VideoPlayer::OpenFile`, `Creating InputStream`) resets it, so it never acts on a
  Kodi that is playing.
- **Trace:** `armed clock=uptime|seconds|none` and `stalled clock|polls <n>s`, reported on the next
  start in `Previous Shield exit guard: …` as before.

## 0.7.9 — 2026-10-11 (prerelease)

Polish from the first week of 0.7.8 on a real TV.

- **Row names you recognise.** Row health and Cached rows show the label the skin gives each row
  (Skin Shortcuts widget groups and `widgetName` properties), with string ids such as `32043`,
  `$LOCALIZE[32043]` and `$ADDON[skin.bingie 32043]` resolved through Kodi, the add-on or the
  skin's strings.po, and say where the row appears ("Home", "Movies hub"). Rows the skin doesn't
  name get a readable name from their path ("Trakt history (movies)", TMDb Helper) instead of
  `plugin.video.tmdb.bingie.helper · trakt_history`. The add-on path stays under Details.
- **Words that match the pages.** The Home rows tile says "46 rows, all working" and how many
  refresh soon or came back empty; a row due a refresh is "Refreshes soon" everywhere, not a
  warning, and "Needs a look" lists failing and empty rows.
- **Memory on Android.** Nearly full swap is normal on Android and stays OK. With swap nearly full
  *and* less than a quarter of memory free, Health and the overview say memory is tight and that
  Android may close Kodi when it is in the background (the Android screensaver or another app).
  Only real shortage still raises a TV notification.
- **Kodi restarts.** The history records when Kodi started; Trends marks each start on the memory
  chart and the overview shows how long Kodi has been running.
- **Readable charts.** X-axis labels are thinned to the width they have, so half-width charts no
  longer print "Sat 10Sun 11".
- **API additions:** `/api/widget-cache` entries carry `title`, `title_from`, `addon_name` and
  `where`; the memory check carries `pressure` (`ok`, `tight`, `low`); `/api/overview` carries
  `kodi_started_at` and `rows.stale` / `rows.empty`; `/api/metrics/history` carries
  `series.kodi_started_at` and `kodi_starts`.

## 0.7.8 — 2026-10-11 (prerelease)

A redesigned dashboard ([design notes](docs/ui.md)). The API only gains endpoints and fields.

- **Overview.** The first screen is drawn as the TV: whether something is playing (and that actions
  which restart Kodi wait for it), the active profile, one verdict ("All good", "2 things need a
  look") with links to whatever needs attention, and tiles for memory, internet, home rows, backups,
  protection and accounts, each with a plain sentence and a 7-day sparkline. It refreshes every
  minute while visible and keeps focus where it was.
- **Trends.** Charts of free memory and Kodi's memory, streaming services' answer times (with
  timed-out checks marked), and failing home rows over 24 hours, 3 or 7 days. Gaps show when the TV
  was busy. Every chart has hover and arrow-key reading and a table view.
- **Row health.** Each cached home row as a card with its first titles' posters, freshness, title
  count, failure streak, last failure and next retry; filter, search and sort, with a fresh / due /
  failing summary bar.
- **Backups** chart checkpoints per day by kind (nightly, manual, playback settings) and list the
  newest first with size; **Health checks** read as a checklist with the problems first and a link to
  where to look next; **Accounts** show sign-in and subscription checks with days left.
- **Navigation by household task:** Status, Home screen, Add-ons & settings, Backups & recovery,
  Accounts, Advanced. Section tabs on every page, a side menu on larger screens, a bottom bar on
  phones, and arrow keys move focus between controls for TV remotes. The old routes still work;
  `#/dashboard` is now the overview and the component table moved to `#/components`.
- **Look and words.** Design tokens with separately chosen light and dark sets and a theme button
  (Automatic, Light, Dark); system fonts; validated, colour-blind-safe chart colours; skeletons while
  loading; empty states that say what to do. API error codes (`playback_active`, `write_disabled`,
  `host_not_allowed`, …) become sentences that say what happened and what to do. View-only profiles
  (writes off, such as a Kids profile) show one calm notice instead of warnings on every page.
- **History on the TV.** The watchdog loop records memory, the newest internet check and cached-row
  counts at most every 15 minutes, only while the TV is idle, into
  `addon_data/service.kodi.addonadmin/metrics_history.json` (7 days, at most 800 samples and 256 KB,
  atomic writes; a damaged file starts afresh).
- **API additions:** `GET /api/overview`, `GET /api/metrics/history?days=1..7`; the internet check
  lists each service's time (`hosts`), account checks carry `days_left`, `/api/widget-cache` entries
  carry `fetched_at` and a six-title `preview`, and checkpoint manifests record `total_bytes`.
- **Demo server:** `scripts/demo_server.py` runs the dashboard against synthetic data on
  127.0.0.1 for design review and screenshots. It is not part of the add-on.

## 0.7.7 — 2026-10-11 (prerelease)

- **Shield exit workaround on Kodi 22.0 RC1.** It was enabled only on 22.0 BETA2, so installing a
  public build on RC1 silently turned it off. It now runs on exactly BETA2 and RC1; RC2 and later stay
  off until checked on a Shield.
- **A stalled exit no longer needs a force-stop.** Quitting with a paused video once left Kodi stuck
  after "Stopping all" for over 90 seconds: the watcher only acted after "Application stopped" and gave
  up after about 30 seconds. Once Kodi has logged "Stopping the application", "Saving skin settings"
  and "Stopping all" in that order, the watcher now ends an exit that has not finished 60 seconds or
  more later. It still never acts before settings are saved. It records its progress, the service
  logs when it is armed on quit, and the next start logs what it saw.
- **Profile changes don't wait on the dashboard.** Stopping the service closes only the listening
  socket and never joins HTTP handler threads.
- **Coordinated profile switches** (setups whose own add-on switches profiles) cancel stale work: the
  service checks for a cancelled generation at start and in its monitor, plugin calls stop rendering,
  and the service acknowledges drained work on exit. Without a coordinator this is a no-op.
- **Private extensions.** A private build can add one optional `household.py` module for its own
  service behaviour, plugin modes and widget-cache modes without patching core files
  ([guide](docs/extensions.md)). Public releases contain none, and the release check refuses one.
- **Boolean settings** are read through Kodi's typed settings API on Kodi 20+, and Write Mode is read
  and written as a bool.
- **Cached rows:** `KM.WidgetFailures` (a Home window property) counts on-screen rows that keep
  failing, with one notice per failure episode while the TV is idle; POV's widget reload token
  refreshes personal rows like TMDb Helper's.
- **Family rows** create offscreen list items, and items that only carry ResumeTime/TotalTime
  properties get a native resume point on Kodi 20+.
- **The dashboard address notice** shows the TV's LAN address instead of `0.0.0.0`, and appears once
  per Kodi session: not after a profile switch or add-on update. It still waits out playback.
- **No checkpoint or protected-setting re-apply during playback.** Both answer `409`
  `playback_active`; a manual checkpoint also stops and is discarded if playback starts while it
  copies.
- **Masked log lines.** `/api/kodi/logs` and the Health page's recent errors and warnings mask tokens,
  keys and bearer headers.
- **DNS-rebinding defence.** Requests whose `Host` is not `localhost`, a `.local` name, a
  loopback/private/link-local IP or the bound address answer `403` `host_not_allowed`. Open the
  dashboard by IP address or `.local` name.
- **installer_result.json** (it holds the access token) is written atomically and owner-only.
- **Tests:** the server concurrency tests poll for state instead of relying on fixed sleeps and
  response-time limits.

## 0.7.6 — 2026-10-11 (prerelease)

- **Restores roll back on failure.** A restore that fails part way (disk full, permission error) puts
  every folder it already changed back from its undo backup; checkpoint restores roll back all
  components. Files are replaced atomically, and a backup that fails is removed instead of
  leaving an unlisted folder that was never pruned.
- **Settings saves are all-or-nothing.** If one setting in a batch (settings editor, playback
  controls, accounts) or Fen Light's settings.db cannot be written, the settings already written are
  put back before the error is reported.
- **Typed settings are checked properly.** Integer settings take whole numbers only; NaN, infinity,
  missing values and objects are refused instead of being stored as text.
- **Playback stays undisturbed.** Watchdog and housekeeping notifications found just before a film
  starts wait for the next quiet moment; the nightly checkpoint stops and discards itself when the TV
  gets busy and retries 10 minutes later; the address notification at service start is skipped while
  something plays; opening add-on or skin settings and Trakt sync from the API are refused while
  playing (`playback_active`).
- **Protected addon.xml values** containing `<`, `>`, `&` or line breaks are refused, so a re-apply
  can no longer leave an add-on's addon.xml malformed.
- **Kodi Manager's own access settings are not restored.** Restoring its folder keeps the live
  `settings.xml` (token, LAN access, Enable writes), so a replaced token cannot come back.
- **Backups and checkpoints copy real files again.** On Kodi, add-on data folders were listed as
  `special://` URLs that file copies cannot open, so per-add-on backups, the snapshot before each
  settings save, nightly checkpoints and pipeline backups copied nothing and restores wrote to the
  wrong place. Paths are now translated, and backups, restores and settings always use the active
  profile's addon_data (the master-profile fallback is diagnostics only).
- **Account checks work on Kodi's Python 3.8.** The TorBox expiry date is parsed without
  `datetime.strptime`, which fails once another add-on has used it, and each account check runs on
  its own so one failure no longer hides the others.
- **Fen Light settings.db numbers are checked like settings.xml ones.** NaN, infinity, overflowing
  values such as `1e999` and Python-only forms such as `1_0` are refused in both places.
- **No stale warnings after a film.** A connection, memory, protected-setting or account problem
  found just as playback started is checked again once the TV is quiet and shown only if it is still
  there, instead of being replayed (for example "Restart the Shield" after the connection had
  recovered). The nightly checkpoint and connection probes also stop when Kodi quits or switches
  profile.
- **Home layout no longer overwrites newer TV changes.** A draft started before the section changed
  on another device or in Kodi's own editor is refused at Review instead of removing the rows added
  there; drafts of untouched sections, and drafts restored from the browser, still apply.
- **Undo toasts expire.** "Restore settings from before this save" and "Undo restore" disappear after
  a minute or on navigation and ask first after 10 seconds, so a stray tap can't roll back later
  changes.
- **Rebuild stays available** after "Stop playback" refuses a skin-menu rebuild.
- **Restore tested fixes and Health Re-apply ask first**, listing what they overwrite.
- A refused settings batch highlights the setting it names; the cached-row Pages field allows 1–5
  like the server; "Layout read only" shows when writes are off; the API docs list
  `playback_active`, `origin_mismatch` and the actual layout fields.
- **Browse and cached rows refuse more add-on actions.** POV/Fen routes that open dialogs or write
  data when run (`options_menu_choice`, `extras_menu_choice`, `watched_unwatched_erase_bookmark`,
  `myservices`, the `*_choice` pickers, `show_text`, view and menu-editor modes) are no longer
  accepted as directory listings.
- **Protected settings obey the write policy.** Capturing or re-applying an add-on item now needs
  the same "Allowed add-ons" permission as the settings editor; only playback, subtitle and library
  Kodi settings can be protected (not network, add-on source, security or display settings); Kodi
  Manager's own and skins' addon.xml cannot be protected; labels are one line of at most 80
  characters. Items saved before these rules are skipped at re-apply and reported as failed.
- **Slow clients cannot lock out the dashboard.** A request line and headers must arrive within 5
  seconds in total (headers cut off by that deadline are never acted on), and one LAN address may
  hold at most 8 of the 16 handler slots.
- **`ManagerClient` reports why a request was refused.** `ManagerError` carries the HTTP `status`
  and the service's error `code` (`write_disabled`, `playback_active`...) with its message, and
  `unsupported` is true only for a 404.
- **Refused setting values name the setting.** A batch save that fails validation answers `<setting
  id>: <reason>` with `details.setting_id` (settings editor, pipeline/account editor and Fen Light
  settings.db), so the dashboard can point at the field to fix.

## 0.7.5 — 2026-10-11 (prerelease)

- Prune backup retention only after the replacement snapshot has completed; failed attempts no longer consume the retention allowance or hide valid backups.
- Repair shared protected files once, preventing duplicate manifest entries from triggering a false conflict and rollback.
- Add optional cached-row genre exclusions and a filtered full-list view without changing source caches or watch history.

## 0.7.4 — 2026-10-10 (prerelease)

- Preserve complete widget rows when later pages fail; retry unavailable or suspiciously empty sources with bounded backoff. Keep the previous successful listing rather than replacing it with partial data.
- Add private-safe cache health records and prioritize visible/active rows during idle refresh.
- Report memory as unknown when MemAvailable is absent. High compressed-swap occupancy alone no longer produces a low-memory warning when RAM is available.

## 0.7.3 — 2026-10-07 (prerelease)

- **Protected settings.** List the values you rely on (an add-on setting, a Kodi setting, or a simple
  element in an add-on's addon.xml such as POV's `reuselanguageinvoker`). Kodi Manager compares them
  shortly after start and every 6 hours, shows a TV notification when an update changed one, and
  Health offers **Re-apply**. API: `GET /api/baseline`, `POST /api/baseline/capture|apply|remove`.
  Security and system settings and Kodi Manager's own settings cannot be protected.
- **Nightly checkpoint.** After 03:00, while the TV is idle, a checkpoint of the add-on stack's settings
  is taken once a night; the newest 7 nightly checkpoints are kept (manual ones are untouched). Restore
  them from Backups like any checkpoint.
- **Account checks.** Twice a day: whether POV's Trakt sign-in is still renewing, and when the TorBox
  subscription ends (warning from 14 days before). Problems show on Health and as one TV notification
  a day.

## 0.7.2 — 2026-10-07 (prerelease)

- **Connection and memory watchdog.** While the TV is quiet, the service checks every 10 minutes that
  the services streaming add-ons rely on (TorBox, Trakt, TMDb) answer a small plain-HTTP request. If most
  of them stop answering on two checks in a row, or memory and swap run low, Kodi shows one
  notification saying what to do (at most every 6 hours), instead of an add-on failing later with a
  timeout. Health lists the last result with each service's response time.

## 0.7.1 — 2026-10-07 (prerelease)

- **Cached rows refresh only while the TV is quiet.** Refreshing runs the source add-on once per row,
  which on a 3 GB device competes with playback start-up. The refresher now waits while anything is
  loaded in the player, while a busy or progress dialog is open (POV searching for sources), while a
  modal dialog is open and for a minute after the last remote press. It pauses between rows, skips the
  full refresh after a failed or very short playback, and runs a full refresh at most every 30 minutes.
- **Long-press on a cached POV title offers Select source, Options… and Extras… again.** JSON-RPC drops
  an add-on's own context menu, so these are rebuilt from the item: Select source opens POV's source
  list instead of auto-playing.
- **Health shows memory pressure:** Kodi's memory use and free memory/swap, with a warning when the
  device is low enough for add-ons to start timing out.

## 0.7.0 — 2026-10-07 (prerelease)

A security, safety and usability release from a full audit. Upgrading is recommended for anyone who
allows LAN access.

### Security and data safety

- **Fixed an API authentication bypass.** POST and PATCH requests whose path did not start with
  `/api/` (or that used an absolute URL) reached the API without a token, and the server answered
  cross-origin requests with `Access-Control-Allow-Origin: *`. Requests are now normalised and routed
  through one table; only `/api/` paths are served, the wildcard CORS header is gone, writes with a
  foreign `Origin` are refused, and responses carry `nosniff`, `no-referrer` and `DENY` framing headers.
- **Fixed a restore that could empty an add-on's data.** Restoring the oldest backup when retention
  was full pruned that backup before copying it back. Restores now protect their source, refuse a
  missing or incomplete snapshot before touching live data, and never follow symlinks.
- **Account and playback-setting writes** now follow the same rules as the settings editor (writes
  enabled, add-on in the stack or in Allowed add-ons) and can never change Kodi Manager's own
  settings. A batch is validated before anything is written, and only the touched files are backed up.
- **Restores wait for playback to stop** (answer `409`, resend with `"force": true` to override).
- **Plugin routes are checked by one validator** for browsing, previews and cached rows: every query
  value and path segment, so actions such as toggles, refreshes and playback cannot run from a
  read-only preview.
- Access tokens are masked in logged request lines and inside logged strings.

### Reliability

- **Settings apply without restarting Kodi.** Changing host, port or Allow LAN access restarts the
  dashboard server; other settings apply at once. Turning on Allow LAN access is enough to listen on
  the network.
- The service survives invalid numbers in settings and a busy port, and shows a notification.
- Kodi 19 (Python 3.8): cached rows no longer fail on Kodi 19's list items, and the layout editor no
  longer uses a Python 3.9-only call.
- The add-on index is rebuilt off to the side and swapped in, so concurrent requests never see it half
  built; full rescans run at most every 5 seconds.
- Cache, cached-rows, backup and layout files are written atomically with per-file locks.
- Health and Logs read only the end of `kodi.log`.
- Automatic row caching keeps skin XML comments and prunes its own backups.
- Fen Light settings database access is unified, opens files read-only or read-write explicitly and
  copes with special characters in paths.

### Dashboard

- **Errors are visible.** Every button and form now shows a notice when something fails, instead of
  doing nothing. Network failures and unexpected replies get a plain message, and a rejected token
  brings up a sign-in form instead of a blank page. Browser alert/confirm/prompt boxes are replaced by
  in-page notices and dialogs.
- **Restore with undo.** Each add-on's settings page has a **Backups** tab; the Backups page lists
  per-add-on backups as well as checkpoints. After any restore, a notice lists the undo backups with an
  **Undo restore** button. When Kodi is busy, the dashboard asks before restoring anyway.
- **Saving settings offers Undo**, and leaving a page with unsaved changes now asks first (also on
  reload or closing the tab).
- **Read-only add-ons** show their settings disabled with the reason Kodi Manager gives.
- **Cached rows page** for the optional widget cache: each row's status, item count and age, refresh,
  add a row from a pasted path, remove a row and copy its cached URL. Rows your skin already reads
  from the cache are listed too.
- **Sign in on other devices:** Setup offers a `http://IP:PORT/#token=…` link. Tokens are only
  accepted from the `#` part of the address and are removed from it straight away.
- **Copy works over plain HTTP** on the LAN, with a select-the-text fallback.
- **Works the same on any setup:** the menu lists only the add-ons found on this Kodi; **Home layout**
  (formerly Bingie Studio) appears only for a skin it supports; Shield- and Bingie-specific wording is
  gone; setting names match Kodi (**Enable writes**, **Allow LAN access**).
- **Security:** no inline event handlers (this fixes script injection through a crafted add-on id on
  the search and All add-ons pages); the page sets a `script-src 'self'` content security policy.
- **Phones and keyboards:** a Menu button replaces the long navigation strip under 760px, tables turn
  into cards, the search box is labelled, the current page and pressed filters are announced, and
  focus moves to each page's heading.
- Fixed: Health showed a literal `\n` between log lines; dead code removed.
- **Add-on:** new icon and fanart; fuller description (it opens Kodi's own Install from zip dialog
  rather than installing ZIPs itself); website, source and disclaimer. Settings are grouped into
  Dashboard, Backups, Cached rows (optional) and Advanced, with every setting id kept; the unused
  **Stack mode** and **Show advanced settings** are gone.

### Packaging and releases

- **Releases:** one version source (`src/kodi_manager/version.py`); `check_release.py` checks every
  archive's version and the add-on ZIP's required files; CI runs all Node tests on Node 20 and the
  test suite on Python 3.8 (Kodi's Python on Android); pushing a `v*` tag builds, checks
  reproducibility and publishes a prerelease with checksums.
- Docs: the [API guide](docs/api.md) lists every endpoint; recovery, compatibility, setup and security
  notes updated.

## 0.6.2 — 2026-10-06 (prerelease)

- Fixed the **Open the dashboard** screen from 0.6.1, found on a real TV: it showed "Busy" instead of
  the address (Kodi answers that while it looks the address up), and the long token was cut off.
  It now waits for the address and shows everything in a full-height text window.

## 0.6.1 — 2026-10-06 (prerelease)

- **Find the dashboard from the TV.** Kodi Manager's add-on folder now opens with **Open the
  dashboard on another device**, which shows the address and access token (or how to turn on LAN
  access). No more reading the token out of `settings.xml`.
- Cached rows moved into a **Cached rows** folder inside the add-on.
- README rewritten around what the add-on does, with measured timings, a diagram and an FAQ.

## 0.6.0 — 2026-10-06 (prerelease)

The widget cache now works with any skin and any video add-on.

- **Cached rows for any skin.** A new **Add to Kodi Manager cached rows** context-menu item on video
  add-on folders saves a row; the Kodi Manager add-on root lists saved rows, so any skin's widget
  picker can choose them. Also `GET/POST /api/widget-cache/rows`, `POST /api/widget-cache/rows/remove`
  and `GET /api/widget-cache/url`.
- **View more for any add-on** whose listing offers another page, using that add-on's own Next page
  artwork. Fen and Fen Light `build_*` list routes are recognised like POV's.
- **Automatic routing for more skins:** Skin Shortcuts `widgetPath` properties are converted as well
  as Bingie widget groups, and **Also route rows from these add-ons** opts other add-ons in.
- **Row item limit** setting for skins that cap rows (0 keeps Bingie detection).
- Fixed: the `port`, `backup_retention` and new numeric settings used an invalid type (`integer`),
  so Kodi ignored their definitions and logged warnings.

## 0.5.5 — 2026-10-06 (prerelease)

- View more stays visible when the skin caps widget rows: Bingie shows at most
  `Skin.String(WidgetsGlobalLimit)` items, so cached rows trim to one less and keep View more last.

## 0.5.4 — 2026-10-06 (prerelease)

- Cached list rows end with a **View more** item that opens the add-on's full, paged listing
  (for TMDb Helper rows, the same list without `widget=true`).
- POV list rows read two pages by default by following POV's own Next page item; a row can ask for
  up to five with `&pages=N` on the cached URL. A failure on a later page keeps the earlier pages.
- `&hide_watched=true` on a cached URL drops watched items for that row only, so "unseen" rows and
  "show everything" rows (a studio, a show's seasons) can live in the same profile.

## 0.5.3 — 2026-10-06 (prerelease)

- Cached TMDb Helper rows follow its **Only resolve strm** setting: when it is on, play items are
  no longer marked playable, matching what TMDb Helper itself does.
- New opt-in setting **Route new skin widget rows through the widget cache**. On start, the
  service rewrites direct POV (`build_*`) and TMDb Helper widget rows in Skin Shortcuts' widget
  groups (`*-10000-1`, `*hub`) to cached URLs, backing up the original files to
  `kodi-manager-backups/autocache-<time>/`. Menus and other add-ons are left alone. Rows switch
  over when Skin Shortcuts next rebuilds the menu.

## 0.5.2 — 2026-10-06 (prerelease)

- Widget cache supports TMDb Helper rows (`plugin.video.themoviedb.helper` and
  `plugin.video.tmdb.bingie.helper`). JSON-RPC drops the properties TMDb Helper sets, so the cache
  restores the ones it derives from data: `<id>_id` for each unique id, `item.<param>` for each
  item URL parameter, `item.type` and `widget`. `info=play` items stay playable (TMDb Helper
  resolves them with setResolvedUrl).
- Personal Trakt rows (`trakt_ondeck*`, `trakt_nextepisodes`, `trakt_history`, `trakt_upnext`,
  watchlists, recommendations…) use the short refresh schedule, and are refreshed whenever
  TMDb Helper bumps its own widget reload property after a Trakt sync.

## 0.5.1 — 2026-10-06 (prerelease)

- Widget cache: Trakt watchlist rows refresh on the short (15 minute / after playback) schedule.
- `cache_url()` drops skin reload counters such as `&reload=$INFO[...]` from the source, so the
  cache key stays stable; the cache's own `km_widgets` counter reloads rows instead.

## 0.5.0 — 2026-10-06 (prerelease)

- **Widget cache.** Point a widget at
  `plugin://service.kodi.addonadmin/?mode=cached&source=<encoded add-on directory>` and Kodi
  Manager serves the row's last listing from disk without calling the source add-on, so rows
  appear without waiting for each add-on call (POV takes 1–2 s per row). The service refreshes stale rows one at a time
  in the background (continue-watching style rows every 15 minutes and after playback stops,
  others every 6 hours, season lists daily), never during playback, and keeps the old listing if a
  refresh fails. Add `&reload=$INFO[Window(Home).Property(km_widgets)]` so the skin reloads rows
  when fresh data changes them. Items keep the source add-on's own URLs and metadata.
- `GET /api/widget-cache` lists cached rows; `POST /api/widget-cache/refresh` queues them all.

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
