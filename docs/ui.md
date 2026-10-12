# Dashboard design

The dashboard answers one question first: **is the TV all right?** Then it lets the person who looks
after the TV fix what is not, from a phone on the sofa, a laptop or the TV's own browser. Everything
is served by the add-on itself: no fonts, scripts or images from the internet (poster previews come
from the same allowlisted artwork hosts the TV already uses, without a referrer).

## Information architecture

Pages are grouped by household task, not by how the add-on is built. Every page has the same
header: a title, one sentence saying what the page is for, and the other pages in its group as tabs.

| Group | Pages (route) | What it answers |
|---|---|---|
| **Status** | Overview `#/dashboard` · Trends `#/trends` · Health checks `#/health` | Is anything wrong right now? Has it been getting worse? |
| **Home screen** | Row health `#/rows` · Home layout `#/widgets` (supported skins) · Cached rows `#/cached-rows` | Are the rows on the TV's home screen filling in? What is on them? |
| **Add-ons & settings** | Your add-ons `#/components` · one page per detected add-on (`#/pov`, `#/skin`, …) · All add-ons `#/addons` · Playback setup `#/pipeline` · Playback test `#/playback-test` · Install `#/install` | What is installed and how is it set up? |
| **Backups & recovery** | Backups `#/backups` · Custom fixes `#/fixes` | Can I get back to how it was? |
| **Accounts** | Accounts `#/accounts` · Trakt `#/trakt` | Will streaming stop working because a sign-in or subscription lapses? |
| **Advanced** | Kodi log `#/kodi-logs` · Service log `#/logs` · Diagnostics `#/diagnostics` · Connection `#/setup` | Detail for troubleshooting. |

Settings search stays in the header on every page; an add-on's settings open at `#/addon/ID`.
Old routes keep working.

**All add-ons** explains each entry's purpose and separates Kodi components, skins, shared
libraries, update repositories, resource packs, video add-ons and services. Search also matches
purposes and dependent add-ons. Type and review filters find disabled entries, background services,
declared dependents and saved configuration. An add-on's settings page repeats its explanation.

Removal hints are advisory: **Keep** marks Kodi components, this dashboard and the active skin;
**Check dependents** lists installed add-ons that import it; **Review disabled** identifies disabled
entries with no declared dependents. Check every profile and any widget, skin-action or player
selection before uninstalling. Installed files may be shared, and a player can select a scraper
without declaring an import. A background-service label describes the manifest, not proof that
the service is running. Removing disabled add-ons mainly saves storage; enabled background
services can also consume RAM. Removal still happens through Kodi's own add-on manager.

### Navigation

- **Phone (under 900 px):** a bottom bar with Status, Home screen, Add-ons, Backups and More. More
  opens the full menu (Accounts and Advanced live there). The current group is highlighted.
- **Tablet and laptop:** a side rail lists every group and page.
- **TV remote:** once something on the page has focus, the arrow keys move focus to the nearest
  control in that direction; Enter activates it. With nothing focused the arrows scroll as usual.
  Every control has a visible focus ring and a tap target of at least 44 px.

## Overview

The first screen is drawn as the TV itself: the "screen" says in plain words what state the TV is in
(idle, or what is playing), which profile is active and whether changes are allowed from here. Below
it, one tile per household concern. Each tile shows a single sentence ("All good", "2 rows failing:
tap to see"), the number that matters, a 7-day sparkline where there is history, and links to the
page that explains it.

| Tile | Number | Trend | Opens |
|---|---|---|---|
| Memory | free memory now | free memory, 7 days | Trends |
| Internet | slowest add-on service now | median answer time, 7 days | Trends |
| Home rows | rows failing / cached | failing rows, 7 days | Row health |
| Backups | time since last checkpoint | checkpoints per day, 14 days | Backups |
| Protection | custom fixes and protected settings | – | Custom fixes / Health |
| Accounts | days until the next expiry | – | Accounts |

The overview refreshes every minute while it is visible and stops while the tab is hidden.

## Charts

Charts are hand-written SVG built from small JSON (`web/charts.js`): no library.

- **Form follows the job.** One current value with a trend is a tile with a sparkline; change over
  time is a line; counts per day are columns. No dual axes: memory free and memory used by Kodi
  share one MB axis; latency gets its own chart.
- **Colour.** Series use the validated categorical order (blue, orange, aqua), checked with the
  palette validator against both card surfaces (all-pairs, light and dark). Status colours (good,
  warning, problem) are reserved for state and always come with an icon and a word. Text never uses a
  series colour.
- **Marks.** 2 px lines, end dots with a surface ring, hairline solid gridlines, columns at most
  24 px wide with a rounded top. Gaps in the data (the TV was busy, or off) break the line instead of
  drawing a straight line across them.
- **Reading values.** Hover or focus a chart and use the arrow keys: a crosshair snaps to the nearest
  sample and one tooltip lists every series. Every chart also has a "Show as table" view, an
  accessible name and a one-line summary, so no value depends on hovering or on colour.

## History on the TV

The service keeps a small history so the charts have something to show:
`addon_data/service.kodi.addonadmin/metrics_history.json` in each Kodi profile.

- Sampled from the existing watchdog loop at most every 15 minutes, **only while the TV is idle**.
  Nothing extra runs during playback, so a film shows as a gap.
- Each sample: free/total memory, Kodi's memory, swap use, the newest internet probe (only when a new
  probe ran since the last sample; probes are not added), and cached-row counts (cached, failing,
  failing three times or more).
- Each sample also records when the Kodi process started, so Trends can mark every restart
  (including Android closing Kodi in the background).
- Kept for 7 days and at most 800 samples (about 100 KB); written atomically, and a damaged file
  starts a fresh history instead of failing.
- Read with `GET /api/metrics/history?days=1..7` ([API](api.md)).

## Words

- Rows are called what the skin calls them (the Skin Shortcuts label, string ids resolved), with
  where they appear; only rows the skin doesn't name fall back to a name built from their path.
- Tile sentences use the same states as the page they open: a row due a refresh "refreshes soon"
  on both, and full swap on Android is explained rather than flagged.
- Say what the household sees: "rows on the home screen", not "widget cache entries".
- Errors say what happened and what to do: `playback_active` reads "Something is playing on the TV.
  Try again when viewing has finished." Every API error code maps to such a sentence
  (`friendlyError` in `web/core.js`).
- Empty states invite the next step ("No checkpoints yet. Create one before changing anything.").
- **View-only profiles** (writes off, for example a Kids profile) show a calm notice once at the top
  and disable the buttons that would change something, with the reason on the button.

## Look

- Design tokens are CSS custom properties in `web/styles.css` (`:root`), with a dark set chosen
  separately rather than inverted. The theme follows the device; the header button cycles Automatic,
  Light and Dark and remembers the choice in this browser.
- System fonts only: rounded system face for headings where the device has one, the system UI face
  for text, tabular figures only in tables and axes.
- One accent (indigo, the glow of a TV in a dark room); the TV-shaped Overview header is the one
  decorative element. Cards are flat with hairline borders; depth comes from the page plane.
- Motion only answers an action (opening a menu, a tooltip) and is off with reduced motion.
