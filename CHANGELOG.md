# Changelog

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
