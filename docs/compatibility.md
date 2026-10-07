# Compatibility and verification

These are alpha releases. Passing a fixture test does not establish live TV compatibility.

| Component | Evidence | Limit |
| --- | --- | --- |
| Library/client | Python 3.9+; Linux/Windows CI on 3.9, 3.11, 3.13; macOS local tests | A computer install does not install the TV service |
| Service code on Kodi's Python | CI runs the test suite on Python 3.8, the version Kodi 19–21 embeds on Android | The library package itself still needs 3.9+ |
| 0.7.0 library/ZIP (current release) | 308 Python and 63 UI tests; Python 3.8 job; Linux/Windows CI; deterministic ZIP and fresh-wheel smoke | — |
| Kodi service, live | 0.4.2–0.6.2 installed and used on an NVIDIA Shield (Kodi 22 beta 2), two profiles, Bingie 2.0.2, POV and TMDb Bingie Helper | One device; other skins and devices are tested in CI only |
| Widget cache | Live on the Shield above: cached rows, View more, multi-page rows, per-row hide watched, background refresh, TMDb Helper playback from a cached row | Needs Kodi 20+ (ListItem info tags). Other skins' `widgetPath` routing and the cached-rows picker are covered by tests, not yet live |
| Kodi service | Requires Kodi `xbmc.python` API 3.0.0 | No universal Kodi/firmware guarantee |
| Layout writes | Reviewed Bingie 2.0.2 and Skin Shortcuts 2.0.3 versions **and source hashes** | Unknown forks/patches are view-only |
| Provider browsing | Enabled installed providers, real directory routes | Provider code may use network/accounts; availability varies |
| Config recovery | Synthetic add-on/stack backup, restore and undo tests | Copies configuration; not APK/Android-data recovery or cloud history |

Start with read-only access and inspect the installed versions/profile. A customized Manager may
contain separate fixes absent here: back it up before replacing it. Confirm the viewer is finished
before TV navigation, restarts or writes. See [recovery](recovery.md), [API](api.md) and
[private security reporting](../SECURITY.md).

Before broad promotion, verify the service on a spare or backed-up device: install through Kodi,
sign in to the dashboard, inspect each profile, check settings, playback setup and backups, then test
one reversible settings change and its undo. Record the device, Android/Kodi/skin versions and actual
results.
