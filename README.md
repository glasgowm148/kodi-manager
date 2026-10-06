<p align="center">
  <img src="docs/images/banner.svg" alt="Kodi Manager — Understand your setup. Shape your Kodi experience." width="100%">
</p>

<p align="center">
  <a href="https://github.com/glasgowm148/kodi-manager/actions/workflows/ci.yml"><img src="https://img.shields.io/github/actions/workflow/status/glasgowm148/kodi-manager/ci.yml?branch=main&amp;style=flat-square&amp;label=CI" alt="CI status"></a>
  <a href="https://github.com/glasgowm148/kodi-manager/releases"><img src="https://img.shields.io/github/v/release/glasgowm148/kodi-manager?include_prereleases&amp;style=flat-square&amp;color=7dd3fc" alt="Latest release, including prereleases"></a>
  <a href="pyproject.toml"><img src="https://img.shields.io/badge/Python-3.9%2B-7dd3fc?style=flat-square" alt="Python library: 3.9 or newer"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-MIT-c4b5fd?style=flat-square" alt="MIT license"></a>
</p>

<p align="center">
  <a href="#what-you-can-do">Features</a> ·
  <a href="#quick-start">Quick start</a> ·
  <a href="#python-library">Python library</a> ·
  <a href="#documentation">Documentation</a>
</p>

**Inspect and configure Kodi from your browser or your own tools.** See which add-ons are enabled, understand the playback pipeline, explore widget sources and manage supported Bingie layouts. Use it independently or as the on-device companion to [nvidia-MCP](https://github.com/glasgowm148/nvidia-MCP).

![Kodi Manager dashboard with component statuses, settings links and backup checkpoints](docs/images/dashboard.png)

*Public dashboard captured with synthetic demo data. No personal accounts, watch history or TV screenshots are included.*

> [!NOTE]
> **Alpha / prerelease.** Use **0.4.2 or later** for bounded backups and one-time installer setup. The portable companion
> still needs live-TV verification; see [compatibility](docs/compatibility.md) and [recovery](docs/recovery.md).

## What you can do

| Feature | What it helps you understand or change |
| --- | --- |
| **Setup dashboard** | Installation, enabled states and saved configuration, with explicit unknown states |
| **Friendly settings** | Add-on schemas, current/default values, searchable controls, and visible, editable account tokens so you can enter and repair them |
| **Playback pipeline** | The selected player, helper routing and evidence for provider/account links |
| **Bingie Studio** | Current menu/hubs, paginated add-on folders, row previews and reviewed layout changes |
| **Configuration recovery** | Add-on/stack backups, restore and diagnostic logs |
| **Python library** | An authenticated API client, offline schema parsing and reusable configuration modules |

<details>
<summary><strong>See the playback pipeline</strong></summary>

![Playback pipeline showing the interface, metadata helper, playback provider and routing evidence](docs/images/pipeline.png)

*Synthetic example showing a Bingie → TMDb Bingie Helper → POV setup. Detected relationships are separate from account authentication.*

</details>

## Which part runs where?

| Part | Runs on | Purpose |
| --- | --- | --- |
| **Kodi service add-on** | Inside Kodi | Reads the live profile/settings and provides the local API |
| **Browser dashboard** | Your computer or another LAN device | Uses that API to inspect and configure Kodi |
| **Python library** | Your computer | Lets scripts and MCP clients use the API or parse schemas offline |

Installing the Python library does **not** install the TV service. The service and library are released separately as a Kodi ZIP and Python wheel, from the same source. No PyPI publication is implied.

## Quick start

**If you use an agent, let it handle the downloads, transfer and computer configuration.** You handle the TV settings and native Kodi installer. Both devices must be on the same home network.

1. **Prepare the TV.** Open Kodi and find the device's local IP. On a Shield, use **Settings → Device
   Preferences → About → Status → IP address**. For agent-assisted transfer, complete the Shield's
   [network-debugging preparation](https://github.com/glasgowm148/nvidia-MCP/blob/main/docs/setup.md).
2. **Hand over to the agent.** Give it the prompt below. It checks existing installations, prepares
   the verified release ZIP and tells you its location on the TV.
3. **Install and enable LAN access in Kodi.** Use **Add-ons → Install from zip file**, then **My
   add-ons → Services → Kodi Manager → Configure**. Enable LAN access, set host `0.0.0.0` and port
   `8765`. Restart when the TV is free; the agent retrieves the token privately and opens the dashboard.

```text
Set up https://github.com/glasgowm148/kodi-manager for my Kodi device.
Read docs/setup.md and handle the computer steps automatically.
Kodi IP: YOUR_KODI_IP
Check for an existing installation and preserve customizations.
Download and verify the companion ZIP, transfer it using authorized access,
and tell me where to select it in Kodi's native installer.
Retrieve the Manager token privately and verify read-only dashboard/API access.
Keep write mode off. Do not interrupt playback.
```
 Prefer to install manually? The [setup guide](docs/setup.md) includes the release download, exact Kodi menus, token location and connection troubleshooting. A bare Kodi installation needs no Bingie skin for general discovery/settings features.

## Faster widget rows

Heavy add-ons can take 1–2 seconds per row before a hub shows anything. Point a skin widget at the
cache instead of the add-on directory:

```
plugin://service.kodi.addonadmin/?mode=cached&source=<URL-encoded add-on directory>&reload=$INFO[Window(Home).Property(km_widgets)]
```

Kodi Manager serves the last listing from disk, refreshes stale rows one at a time in the
background (never during playback), and bumps `Window(Home).Property(km_widgets)` when fresh data
changes, so the skin reloads the row. `kodi_manager.widget_cache.cache_url(source)` builds the URL.

## Making changes

**Write mode starts disabled.** Enable it in the service settings when ready to change configuration; Python clients also need `allow_writes=True`. Layout writes require reviewed **Bingie 2.0.2 / Skin Shortcuts 2.0.3 source hashes**. Unknown variants stay view-only.

Use a trusted LAN: the bearer-authenticated HTTP service is unencrypted and should not be exposed to the internet. Backups and account/log diagnostics are private and can contain credentials.

This release ships Manager code, not household settings, cloud accounts/history or third-party provider/skin patch bundles. Account controls edit installed add-on settings; cloud signup/OAuth and Trakt history migration are separate workflows. See [API boundaries](docs/api.md).

## Python library

Use **Python 3.9+**. The library has no runtime dependencies. Install the wheel from [Releases](https://github.com/glasgowm148/kodi-manager/releases), or use the source instructions below.

```python
import os
from kodi_manager import ManagerClient

manager = ManagerClient("http://192.168.1.50:8765", os.environ["KODI_MANAGER_TOKEN"])
print(manager.status())
print(manager.pipeline())
print(manager.layout())
```
 Use your device's address. `ManagerClient` also exposes health, add-ons, settings, sources, bounded folder browsing and layout preview/apply. Handle `ManagerError`; the client bounds responses and rejects redirects. See the [API guide](docs/api.md) for the preview/apply workflow and operation rules.

<details>
<summary><strong>Install from source and parse settings offline</strong></summary>

```sh
git clone https://github.com/glasgowm148/kodi-manager.git
cd kodi-manager
python3 -m venv .venv
.venv/bin/python -m pip install .
```
 On Windows use `py -3 -m venv .venv` and `.venv\Scripts\python.exe`.

```python
from kodi_manager import parse_schema, flatten_settings

schema = parse_schema("addon/resources/settings.xml", "addon", "userdata/settings.xml")
settings = flatten_settings(schema)  # Secret values are masked.
```
 The top-level client/parser exports are the public interface. Internal runtime modules such as `server`, `pipeline` and `skin_layout` need Kodi's `xbmc` runtime or an application-supplied adapter; their interfaces may change during alpha.

</details>

## Documentation

| Guide | Use it for |
| --- | --- |
| [Setup](docs/setup.md) | TV installation, agent computer steps and connection troubleshooting |
| [API](docs/api.md) | Endpoints, authentication, layout workflows and runtime boundaries |
| [Compatibility](docs/compatibility.md) | Reviewed skin versions, test evidence and remaining live checks |
| [Recovery](docs/recovery.md) | Backup, restore and upgrade preparation |
| [Contributing](CONTRIBUTING.md) · [Changelog](CHANGELOG.md) | Development, packaging and release checks |
| [Security](SECURITY.md) | Private diagnostics and vulnerability reports |

The library and Kodi ZIP share `src/kodi_manager`; browser assets live in `web/`. CI checks Python and UI tests, fresh-wheel installation and release contents. Development commands are in [Contributing](CONTRIBUTING.md).

---

[MIT license](LICENSE). Independent project; not affiliated with Kodi or NVIDIA. Provider add-ons and accounts are supplied by the user.
