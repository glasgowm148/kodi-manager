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
  <a href="#questions">Questions</a> ·
  <a href="#for-developers">Developers</a>
</p>

**Inspect and configure Kodi from your browser.** Kodi Manager is a Kodi add-on with a local web
dashboard. It shows which add-ons are installed and enabled, how playback is wired from skin to
player, and what each add-on is set to. You can then change settings, back them up and restore them
from a phone or computer. Use it on its own or as the on-device companion to
[nvidia-MCP](https://github.com/glasgowm148/nvidia-MCP).

![Kodi Manager dashboard with component statuses, settings links and backup checkpoints](docs/images/dashboard.png)

*Captured with synthetic demo data. No personal accounts, watch history or TV screenshots are included.*

> [!NOTE]
> **Prerelease.** 0.6.2 is in use on an NVIDIA Shield with Kodi 22 beta 2 and the Bingie skin.
> Other skins and devices are covered by automated tests rather than live use so far; see
> [compatibility](docs/compatibility.md).

## What you can do

| Feature | What it shows or changes | Works with |
| --- | --- | --- |
| **Setup overview** | Installed and enabled add-ons and saved configuration; anything it can't confirm is marked unknown | Any Kodi 19+ |
| **Settings** | Each add-on's settings with current and default values, searchable. Account tokens are visible so you can enter and repair them | Any Kodi 19+ |
| **Playback pipeline** | Which player is selected, how metadata helpers route to it, and evidence for provider and account links | Any Kodi 19+ |
| **Backups** | Add-on and whole-setup checkpoints, restore with undo, diagnostic logs | Any Kodi 19+ |
| **Layout editor** | Previews hub and row changes, and applies them after you review them | Bingie 2.0.2 with Skin Shortcuts 2.0.3 |
| **Faster rows** (optional) | Serves home-screen rows from a cache and adds **View more** to each list ([guide](docs/widget-cache.md)) | Any skin, Kodi 20+ |
| **Python library** | API client and offline settings parser for scripts and MCP clients | Python 3.9+ |

<details>
<summary><strong>See the playback pipeline</strong></summary>

![Playback pipeline showing the interface, metadata helper, playback provider and routing evidence](docs/images/pipeline.png)

*Synthetic example: Bingie → TMDb Bingie Helper → POV. Detected relationships are separate from account authentication.*

</details>

## Quick start

1. **Download** `service.kodi.addonadmin-<version>.zip` from
   [Releases](https://github.com/glasgowm148/kodi-manager/releases).
2. **Install it.** In Kodi, choose **Add-ons → Install from zip file** and pick the ZIP. Allow
   unknown sources if Kodi asks.
3. **Allow the dashboard on your network.** Go to **Add-ons → My add-ons → Services → Kodi Manager →
   Configure**. Turn on **LAN access**, set host `0.0.0.0` and port `8765`, then restart Kodi.
4. **Open the dashboard.** In Kodi, open **Add-ons → Video add-ons → Kodi Manager → Open the
   dashboard on another device**. It shows the address and access token to use in a browser.

The [setup guide](docs/setup.md) has menu-by-menu steps and troubleshooting.

<details>
<summary><strong>Let an AI agent do the computer side</strong></summary>

You handle the TV and Kodi's installer; the agent downloads, verifies and transfers the ZIP and
connects to the dashboard. On a Shield, complete nvidia-MCP's
[network-debugging preparation](https://github.com/glasgowm148/nvidia-MCP/blob/main/docs/setup.md) first.

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

</details>

## Optional: faster home-screen rows

Heavy add-ons can take 1–3 seconds per row before a home screen fills in. Kodi Manager can serve
rows from a cache instead, so they appear in about half a second, and refresh them in the
background. To use it, open an add-on folder, choose **Add to Kodi Manager cached rows** from its
context menu, then pick it in your skin's row picker under **Kodi Manager → Cached rows**. Skin
Shortcuts skins can switch existing rows over automatically. See the
[widget cache guide](docs/widget-cache.md).

## Questions

**Do I need a particular skin or add-on?**
No. The dashboard, settings, pipeline and backups work with any skin. Only the layout editor is
Bingie-specific.

**Does it change anything by itself?**
No. Write mode starts off, so the dashboard can only look until you turn it on in the add-on's
settings. Settings and layout changes take a backup first, and installs and menu rebuilds refuse to
run while something is playing. The optional row cache only switches rows over if you turn that on.

**Which Kodi versions?**
Kodi 19 or newer; the optional row cache needs Kodi 20. It's tested on Kodi 22 beta 2; see
[compatibility](docs/compatibility.md).

**Is it safe on my network?**
Keep it on your home network. The dashboard uses an access token over plain HTTP, so don't expose it
to the internet. Backups and diagnostics can contain credentials. Releases contain Kodi Manager's
code only: no accounts, watch history or third-party add-on patches.

**How do I remove it?**
Uninstall it from **Add-ons → My add-ons → Services**. If you used cached rows, switch those rows
back first; the [widget cache guide](docs/widget-cache.md#manage-and-undo) explains how.

## For developers

The same code ships as a Python library with no dependencies (Python 3.9+), for scripts and MCP
clients such as [nvidia-MCP](https://github.com/glasgowm148/nvidia-MCP).

```python
import os
from kodi_manager import ManagerClient

manager = ManagerClient("http://192.168.1.50:8765", os.environ["KODI_MANAGER_TOKEN"])
print(manager.status())
print(manager.pipeline())
```

`ManagerClient` also covers health, add-ons, settings, sources, folder browsing and layout
preview/apply; writes need `allow_writes=True`. The [API guide](docs/api.md) lists every endpoint.

<details>
<summary><strong>Install from source, parse settings offline</strong></summary>

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

`ManagerClient`, `parse_schema` and `flatten_settings` are the public interface. Modules such as
`server` and `widget_cache` expect Kodi's runtime and may change before 1.0.

</details>

| Guide | Use it for |
| --- | --- |
| [Setup](docs/setup.md) | Installing, the access token, connection troubleshooting |
| [Widget cache](docs/widget-cache.md) | Row options, refresh schedule, limits, undo |
| [API](docs/api.md) | Endpoints, authentication, layout workflows |
| [Compatibility](docs/compatibility.md) | What has been tested live and what only in CI |
| [Recovery](docs/recovery.md) | Backup, restore and upgrades |
| [Contributing](CONTRIBUTING.md) · [Changelog](CHANGELOG.md) · [Security](SECURITY.md) | Development, release notes, private reports |

---

[MIT license](LICENSE). Independent project; not affiliated with the Kodi Foundation, NVIDIA or any add-on author. You supply your own add-ons and accounts.
