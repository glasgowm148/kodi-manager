# Widget cache

Skins fill each home-screen row by calling a video add-on. Heavy add-ons (Fen, POV, TMDb Helper and
similar) spend 1–3 seconds per row before anything appears, and a hub asks for all its rows at
once. The widget cache serves each row from its last listing on disk instead, so rows appear in
about half a second, and refreshes them one at a time in the background.

It works with any skin and any video add-on. It needs Kodi 20 or newer.

## Add a row

There are three ways. They all produce the same cached row.

### From any add-on folder (any skin)

1. In Kodi, open the add-on folder you want as a row: a film list, a Trakt list, a genre.
2. Open the context menu (long-press OK, or `C`) and choose **Add to Kodi Manager cached rows**.
   Give the row a name.
3. In your skin's widget or row picker, browse to **Add-ons → Kodi Manager** and pick the row.

The Kodi Manager add-on folder lists every saved row for the current profile.

### By pasting a path

Skins with a "custom widget path" field accept a cached path directly:

```
plugin://service.kodi.addonadmin/?mode=cached&source=<URL-encoded add-on folder>&reload=$INFO[Window(Home).Property(km_widgets)]
```

`GET /api/widget-cache/url?source=<add-on folder>` builds it for you.

### Automatically (Skin Shortcuts skins)

Turn on **Route new skin widget rows through the widget cache** in Kodi Manager's settings. Each
time Kodi starts, Kodi Manager switches direct rows over to cached ones. The skin picks up the
change the next time it rebuilds its menu, usually the next start or profile switch.

- **Skins covered.** It understands skins that keep a `widgetPath` per menu item (most Skin
  Shortcuts skins), and Bingie-style widget groups (`*-10000-1`, `*hub`).
- **Add-ons covered by default:** Fen, Fen Light and POV `build_*` lists, and TMDb Helper widget
  rows.
- **Other add-ons:** list their IDs under **Also route rows from these add-ons**, for example
  `plugin.video.example`.
- **Never touched:** live TV, music and library rows, menus, and rows already cached.
- **Backups.** The original files are copied to
  `addon_data/script.skinshortcuts/kodi-manager-backups/autocache-<time>/` first.

## Row options

Add these to a cached path:

| Option | Effect |
| --- | --- |
| `&pages=N` | Read N pages (1–5) by following the add-on's own Next page item. Fen, Fen Light and POV lists read 2 by default; other rows read 1. |
| `&hide_watched=true` | Leave watched items out of this row only. Useful for "unseen films" rows next to "everything by this studio" rows. |

## What every cached row gets

- **View more.** A final item that opens the add-on's full, paged list. It appears whenever the
  add-on offered another page, and always for known list routes. It uses the add-on's own Next page
  artwork.
- **Background refresh.** Rows refresh one at a time, never during playback:

  | Row type | Refreshed |
  | --- | --- |
  | Progress rows: continue watching, watchlists, recommendations | Every 15 minutes, 5 seconds after playback stops, and when TMDb Helper finishes a Trakt sync |
  | Other lists | Every 6 hours, plus one pass 2 minutes after playback |
  | Season and episode lists | Daily |

- **Live reload.** When fresh data differs, Kodi Manager bumps
  `Window(Home).Property(km_widgets)` and the skin reloads the row.
- **Fallback.** If a refresh fails, the last good listing stays. Rows unused for 3 weeks are
  dropped.

## Row item limit

Many skins show only so many items per row. Set **Row item limit** to that number so the View more
item is never cut off. With 0, Kodi Manager uses Bingie's own limit
(`Skin.String(WidgetsGlobalLimit)`) when it finds one.

## Limits

- **Context menus.** Listings are read through Kodi's JSON-RPC. Titles, artwork, ratings, cast,
  resume points, watched state and IDs are kept, but an add-on's own context menu is not. Kodi
  Manager adds watchlist, browse-show and "already watched" entries where it can.
- **TMDb Helper.** Kodi Manager restores the `<id>_id`, `item.*` and `widget` properties skins read.
  It keeps play items playable, following TMDb Helper's **Only resolve strm** setting.
- **Freshness.** Rows can be up to one refresh interval old. Each row still costs about 0.5 seconds,
  because Kodi starts a Python interpreter per call.
- **First load.** A row's first load is slower, because it fills the cache.

## Manage and undo

| Task | How |
| --- | --- |
| See cached rows and their age | `GET /api/widget-cache` |
| Refresh everything now | `POST /api/widget-cache/refresh` |
| List, add or remove picker rows | `GET/POST /api/widget-cache/rows`, `POST /api/widget-cache/rows/remove` |
| Undo automatic routing | Copy the files from the `autocache-<time>` backup back into `addon_data/script.skinshortcuts/` |
| Clear the cache | Delete `addon_data/service.kodi.addonadmin/widget_cache/entries/` |

See the [API guide](api.md) for authentication.

## Kodi 22 beta note

Kodi 22 beta 2 can crash when an add-on that reuses its Python interpreter (POV, for example) is
asked for several rows at once. Once rows are cached, the source add-on is only called by the
background refresher, one row at a time. A row's first load still calls it directly, so if you see
crashes, turn off the add-on's "reuse language invoker" option.
