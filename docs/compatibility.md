# Compatibility and verification

These are alpha releases. Passing a fixture test does not establish live TV compatibility.

| Component | Evidence | Limit |
| --- | --- | --- |
| Library/client | Python 3.9+; Linux/Windows CI on 3.9, 3.11, 3.13; macOS local tests | A computer install does not install the TV service |
| Published 0.4.0 wheel | Fresh macOS venv: import/client and synthetic local HTTP checks | Same-second recovery bug fixed in 0.4.1 |
| 0.4.1 library/ZIP | 158 Python and 47 UI tests; deterministic ZIP, fresh-wheel smoke and restore/undo | Portable companion not yet installed/tested on a live TV |
| Kodi service | Requires Kodi `xbmc.python` API 3.0.0; predecessor used on Shield/Kodi 22 beta 2 | No universal Kodi/firmware guarantee |
| Layout writes | Reviewed Bingie 2.0.2 and Skin Shortcuts 2.0.3 versions **and source hashes** | Unknown forks/patches are view-only |
| Provider browsing | Enabled installed providers, real directory routes | Provider code may use network/accounts; availability varies |
| Config recovery | Synthetic add-on/stack backup, restore and undo tests | Copies configuration; not APK/Android-data recovery or cloud history |

Start with read-only access and inspect the installed versions/profile. A customized Manager may
contain separate fixes absent here: back it up before replacing it. Confirm the viewer is finished
before TV navigation, restarts or writes. See [recovery](recovery.md), [API](api.md) and
[private security reporting](../SECURITY.md).

Before broad promotion, verify the portable service on a spare or backed-up Shield: install through
Kodi, authenticate, inspect both profiles, check settings/pipeline/provider rows, then test one
reversible layout edit and restore. Record model, Android/Kodi/skin versions and actual results.
