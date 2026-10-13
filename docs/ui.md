# Dashboard design

The dashboard starts with **what needs attention and what do you want to manage?** It gives the person who looks
after the TV direct next steps, from a phone on the sofa, a laptop or the TV's own browser. Everything
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
- **Tablet and laptop:** the side rail has six expandable task groups. The current group opens
  automatically. Individual add-on shortcuts sit inside a second disclosure, keeping common tasks visible.
  Direct links and browser Back still reach every existing page.
- **TV remote:** once something on the page has focus, the arrow keys move focus to the nearest
  control in that direction; Enter activates it. With nothing focused the arrows scroll as usual.
  Every control has a visible focus ring and a tap target of at least 44 px.

## Overview

The overview has five parts, in this order:

1. **Your Kodi:** playback state, active profile, whether changes are allowed and when the check ran.
2. **Needs attention:** current device/service check failures, ordered by severity, with a specific
   next step. Missing results are described as unavailable; they never produce an “all good” verdict.
3. **Manage your Kodi:** add-ons, home screen, playback, accounts, backups and add-on settings.
   Home layout editing appears only for supported skins. Read-only profiles can browse these pages.
4. **Recent log activity:** retained 24-hour counts and a link to grouped issues. These are historical
   observations, not proof that the TV is currently failing. Missing collection is stated explicitly.
5. **Device & services:** all six detailed status cards and trends remain available below the tasks.

| Tile | Number | Trend | Opens |
|---|---|---|---|
| Memory | free memory now | free memory, 7 days | Trends |
| Internet | slowest add-on service now | median answer time, 7 days | Trends |
| Home rows | rows failing / cached | failing rows, 7 days | Row health |
| Backups | time since last checkpoint | checkpoints per day, 14 days | Backups |
| Protection | custom fixes and protected settings | – | Custom fixes / Health |
| Accounts | days until the next expiry | – | Accounts |

The overview refreshes every minute while visible, skips hidden tabs and preserves focus on its
actions. Refresh also updates the active profile’s read-only state. Network check failures name the
affected services rather than recommending an immediate TV/router restart.

## Health checks

Current faults and unavailable checks appear first. Retained log issues have their own section
with a clear 24-hour timeframe. Passed checks, setup/access information and detailed device
figures are expandable, so nothing is removed to make the page shorter.

Read-only mode is an intentional configuration. Recognised integrations are optional: a device
does not need Fen, Fen Light, POV and CocoScrapers together to be healthy. Both checks use
`info` status and do not raise overall health severity. Real log errors retain their severity.

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

## Kodi warnings and errors

Health's log scan covers the past 24 hours. **Kodi log** shows retained warnings, errors and known
notices, with level filters and **Load older entries** to page through the complete history.
Entries survive Kodi restarts and profile changes, are masked before storage, and expire after
24 hours. **Current raw log tail** separately shows the newest 500 lines, including info messages.
Initial importing and collection failures are shown. Earlier problems can only be recovered from
log files still available when collection starts; missing old logs cannot be reconstructed.

Issue groups show recorded-entry counts, first/last seen, source evidence and suggested
next steps. Open a group's entries to inspect every occurrence, or expand **Original retained
entries** for the complete list. Groups have their own **Load more issue groups** button.
Counts describe saved lines; Kodi's suppressed-duplicate summaries remain separate when their
original cause cannot be established. Source labels distinguish an identified script, a referenced
add-on, a native Kodi component and an unconfirmed source.

With writes enabled, **Mark reviewed** records a comparison point after checking or fixing an
issue. Later entries show recurrence; earlier entries and Health's totals stay intact until expiry.
Review points are shared across profiles along with the history. Automatic comparison points
record when a Manager version first begins collecting, which can be later than installation or
Kodi startup; they do not prove that an add-on fix succeeded. Health keeps its original severity
and shows a short issue overview. Older histories are grouped in bounded batches with progress
shown while summaries are incomplete.
