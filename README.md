# Kodi Manager

A reusable **Python library**, **Kodi service add-on** and **local browser dashboard** for inspecting
and configuring Kodi. It is the optional on-device companion to
[nvidia-MCP](https://github.com/glasgowm148/nvidia-MCP), and can also be used independently.

The Python library runs on a computer. The companion runs **inside Kodi**, where it can access live
add-on settings, profile paths and skin information unavailable through standard remote JSON-RPC.
Installing the Python library alone does not install anything on a TV.

## What it adds

- Add-on/schema discovery, friendly settings, default/current values and masked credentials.
- Player/provider/account pipeline inspection, including POV and both TMDb Helper variants.
- Bingie menu/hub inspection, paginated provider folders and row previews; previewed layout edits,
  revision checks and backups for supported skin versions.
- Add-on and stack configuration backups, restore, logs and diagnostic pages.
- A family-filter directory helper, plus reusable settings, validation, path and layout modules.

The public version contains original Manager code and synthetic tests. It contains **no personal
accounts, watch history, device settings, vendor add-ons or household-specific third-party patches**.
The Custom fixes page reports that no fixes are bundled. Installing this does not reproduce every
playback/skin patch applied to the original household setup.

## Install the Kodi companion

1. Download `service.kodi.addonadmin-0.4.0.zip` from the
   [release](https://github.com/glasgowm148/kodi-manager/releases/tag/v0.4.0), and verify its accompanying
   SHA-256 file if transferring it through another system.
2. Copy the ZIP to storage Kodi can access. In Kodi enable **Settings → System → Add-ons → Unknown
   sources**, then **Add-ons → Install from zip file** and select it. This uses Kodi's installer rather
   than copying files behind its add-on database.
3. Open **My add-ons → Services → Kodi Manager → Configure**. For access from another computer,
   enable LAN access and set the bind host to `0.0.0.0` (port `8765`). The default is loopback only.
4. Restart the service/Kodi when the TV is free. Open `http://YOUR_KODI_IP:8765`.
5. Enter the generated bearer token. It is in the active profile's
   `addon_data/service.kodi.addonadmin/settings.xml`, under `auth_token`. Read it privately from local,
   mounted or ADB-accessible Kodi storage. It is separate from Kodi's HTTP password.

**Write mode starts disabled.** Enable it in the service settings only when making changes. API
clients can also require their own write opt-in. Backups are private and can contain credentials.
Use a trusted LAN; do not expose the HTTP service to the internet.

Generic discovery/settings do not require Bingie. Layout writes recognize reviewed **Bingie 2.0.2 /
Skin Shortcuts 2.0.3 source hashes**; unknown variants are view-only. Existing custom installations
should be backed up before upgrading: this portable release deliberately omits their patch bundles.

## Use as a Python library

Python 3.9+, no runtime dependencies. Install the release wheel, or install from source:

```sh
git clone https://github.com/glasgowm148/kodi-manager.git
cd kodi-manager
python3 -m venv .venv
.venv/bin/python -m pip install .
```

On Windows use `py -3 -m venv .venv` and `.venv\Scripts\python.exe`.

```python
import os
from kodi_manager import ManagerClient

manager = ManagerClient("http://192.168.1.50:8765", os.environ["KODI_MANAGER_TOKEN"])
print(manager.status())
print(manager.pipeline())
print(manager.layout())
print(manager.sources())
# A bounded preview executes the installed provider's code:
# manager.browse("plugin://plugin.video.pov/", limit=24)
```

`ManagerClient` has status, health, pipeline, addons, settings, layout, sources, browse and layout
preview/apply methods. `request()` supports other documented `/api/` endpoints, rejects redirects,
does not use environment proxies, and bounds requests/responses. Writes require `allow_writes=True`
and the companion's write mode. Handle `ManagerError`; errors do not include tokens or response bodies.
See [the API guide](docs/api.md) for live/offline boundaries and a layout workflow.

Offline schema parsing is also available without Kodi:

```python
from kodi_manager import parse_schema, flatten_settings

schema = parse_schema("addon/resources/settings.xml", "addon", "userdata/settings.xml")
settings = flatten_settings(schema)  # Secret values are masked.
```

`kodi_manager.server`, `pipeline`, `skin_layout`, `widget_catalog` and adapters are reusable internal
modules accepting a Kodi API adapter. Live calls require Kodi's `xbmc` runtime or an adapter supplied
by the application. Their internals may change during alpha; the top-level client/parser exports are
the intended public interface. No PyPI publication is implied; releases provide installable wheels.

## Build and test

```sh
.venv/bin/python -m pip install -e '.[dev]'
.venv/bin/pytest -q
.venv/bin/ruff check .
node --test tests/*.js
.venv/bin/python -m build
.venv/bin/python scripts/build_addon.py
```

The library and Kodi ZIP share `src/kodi_manager`; the browser assets have one source in `web/`.
The deterministic companion builder uses an explicit resource allowlist and verifies matching
versions. Tests use stubs/temporary folders/local HTTP, not a real TV. CI builds Linux/Windows
Python 3.9, 3.11 and 3.13. Compatibility beyond the original Kodi 22 beta 2 setup is not yet live-tested.

MIT licensed. Not affiliated with Kodi or NVIDIA. Provider add-ons/accounts are supplied by the user.
