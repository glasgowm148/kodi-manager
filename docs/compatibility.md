# Compatibility and verification

These are alpha releases. Passing a fixture test does not establish live TV compatibility.

| Component | Evidence | Limit |
| --- | --- | --- |
| Library/client | Python 3.9+; Linux/Windows CI on 3.9, 3.11, 3.13; macOS local tests | A computer install does not install the TV service |
| Service code on Kodi's Python | CI runs the test suite on Python 3.8, the version Kodi 19–21 embeds on Android | The library package itself still needs 3.9+ |
| 0.7.27 library/ZIP (current release) | Add-on explanations/dependencies, retained masked 24-hour logs, missing metadata and native-object lifetime checks, service startup/abort regression; earlier auth/profile/backup/tvOS safeguards retained. 835 Python tests passed (one environment skip), 104 UI tests, lint/type checks, isolated wheel smoke and deterministic ZIP/archive checks | Public ZIP not installed on the Shield; check this tag’s CI results |
| Kodi service, live | Household 0.7.27 on an NVIDIA Shield, Kodi 22 RC1, two profiles and Bingie 2.0.2.5: retained history survives updates/restarts, metadata browsing and automatic profile round trip verified | One customized device with separate household/provider patches; public ZIP installation on other devices is unverified |
| Shield exit workaround | Opt-in; enabled only on Android Kodi 22.0 BETA2 and RC1 with NVIDIA's driver. Ends the exit after Kodi has saved its settings: at skin unload, or more than 60 s (boot clock; 3000 polls as a fallback) stalled after "Stopping all". Armed when Kodi announces the quit | RC2 and later, and the final release, stay disabled until checked on a Shield |
| Widget cache | Live on the Shield above: cached rows, View more, multi-page rows, per-row hide watched, background refresh, TMDb Helper playback from a cached row | Needs Kodi 20+ (ListItem info tags). Other skins' `widgetPath` routing and the cached-rows picker are covered by tests, not yet live |
| Android TV / Google TV / Android-based Fire OS | Uses public Kodi Python APIs and resolved storage paths; NVIDIA exit gate covered by synthetic tests | Public ZIP installation, performance and hardware behavior unverified on these devices; Vega OS unsupported |
| Apple TV / tvOS | 0.7.23 synthetic virtual/physical XML routing, nested-profile confinement, read/write/rollback, backup/restore/undo/pruning, pipeline-file capture, authenticated bounded reads and inactive-action refusal | Experimental; no physical Apple TV tests. Native active state must be readable; tvOS backup/cache manifests can be purged. See [tvOS guide](apple-tv.md) |
| Kodi service | Requires Kodi `xbmc.python` API 3.0.0 | No universal Kodi/firmware guarantee |
| Layout writes | Reviewed Bingie 2.0.2 and Skin Shortcuts 2.0.3 versions **and source hashes** | Unknown forks/patches are view-only |
| Provider browsing | Enabled installed providers, real directory routes; POV, Fen, Fen Light, TMDb Helper, BBC iPlayer and Bingie Widgets limited to an allowlist of their listing routes, checked against 9,383 plugin URLs from one household TV | Provider code may use network/accounts; availability varies; other add-ons are checked for action words only |
| Config recovery | Synthetic add-on/stack backup, restore and undo tests | Copies configuration; not APK/Android-data recovery or cloud history |

Start with read-only access and inspect the installed versions/profile. A customized Manager may
contain separate fixes absent here: back it up before replacing it. Confirm the viewer is finished
before TV navigation, restarts or writes. See [recovery](recovery.md), [API](api.md) and
[private security reporting](../SECURITY.md).

Before broad promotion, verify the service on a spare or backed-up device: install through Kodi,
sign in to the dashboard, inspect each profile, check settings, playback setup and backups, then test
one reversible settings change and its undo. Record the device, Android/Kodi/skin versions and actual
results.
