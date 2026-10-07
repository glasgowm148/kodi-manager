# Changelog

## Unreleased

Dashboard, packaging and release work. Backend changes are listed separately.

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
  add a row from a pasted path, remove a row and copy its cached URL.
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
