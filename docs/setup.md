# Install Kodi Manager

Kodi Manager has a **TV service**, **browser dashboard** and **computer-side Python library**.
For live settings/dashboard access, install the service ZIP inside Kodi. Installing the library on
your computer alone does not install or start the TV service.

The current portable release is **0.7.29**, marked prerelease. See [compatibility](compatibility.md)
for remaining live checks. Back up an existing customized installation before upgrading: public
releases deliberately omit household settings and separate third-party patch bundles.

For **Apple TV**, follow [tvOS installation and recovery](apple-tv.md). Install from a Kodi-readable network source, enable LAN access, enter the token privately and keep Kodi active. Android transfer/forwarding instructions below do not apply.

## Before you start — on the TV

1. Open Kodi on the device you want to manage. The TV and computer should be on the same home network.
2. Find its local IPv4 address. On a Shield: **Home → Settings gear → Device Preferences → About →
   Status → IP address**. Older firmware may put About directly under Settings. On Fire OS use **Settings → My Fire TV →
   About → Network**; on Google TV use the connected **Network & Internet** entry or About/Status.
3. If an agent will transfer files or read the token through ADB, enable the device’s **Network
   debugging**, **ADB Debugging** (Fire OS), or paired **Wireless debugging** (Google TV).
   Follow [Android TV / Fire TV preparation](https://github.com/glasgowm148/nvidia-MCP/blob/main/docs/android-tv.md)
   for device-specific menus and pairing/connection ports. Approve the debugging prompt
   when the agent connects. A mounted/local Kodi storage path is another option.
4. Confirm viewing has finished before TV navigation, installation or restarting Kodi.

Kodi's separate HTTP control service is needed for nvidia-MCP's Kodi RPC tools, but is not required
for the Manager dashboard alone.

## Let an AI agent handle the computer side

You handle the TV and Kodi's installer; the agent downloads, verifies and transfers the ZIP and
connects to the dashboard. If using ADB for transfer on Android TV or Fire OS, complete the
[device debugging preparation](https://github.com/glasgowm148/nvidia-MCP/blob/main/docs/android-tv.md) first.
Manual installation or transfer through a Kodi-readable share does not require ADB or nvidia-MCP.

```text
Set up https://github.com/glasgowm148/kodi-manager for my Kodi device.
Read docs/setup.md and handle the computer steps automatically.
Kodi IP: YOUR_KODI_IP
Check for an existing installation and preserve customizations.
Download and verify the companion ZIP, transfer it using authorized access,
and tell me where to select it in Kodi's native installer.
Retrieve the Manager token privately and verify read-only dashboard/API access.
Keep Enable writes off. Do not interrupt playback.
```

## Prepare the release — agent/computer

An agent with terminal/file access should perform these steps rather than handing the user commands
or JSON editing tasks. Ask only for missing connection information or unavoidable TV actions.

1. Check for an existing Manager installation and inspect its version/profile before replacing it.
   Preserve local changes and create an appropriate private backup for an authorized upgrade.
2. Download `service.kodi.addonadmin-0.7.29.zip` and `SHA256SUMS` from the release's **Assets** at
   [v0.7.29](https://github.com/glasgowm148/kodi-manager/releases/tag/v0.7.29). Verify the ZIP checksum.
   GitHub's **Source code** ZIP, Python wheel and tar.gz cannot be installed through Kodi.
   nvidia-MCP users can instead export the pinned bundle with `nvidia-mcp --export-manager DIRECTORY`.
3. Transfer the verified ZIP to a Kodi-accessible folder using authorized ADB, a mounted share or
   local storage. Use only the configured device, not a LAN scan. Give the user the exact folder and
   file name to select. If no transfer route is available, explain the specific manual copy needed.

## Verify the download

On the computer, save both release assets in one folder and run this Python snippet from that folder.
An agent should perform this check before transferring the ZIP. To check a wheel instead, change `name`
to that asset's filename. A missing entry or mismatched digest means stop and download again.

```python
import hashlib
from pathlib import Path

name = "service.kodi.addonadmin-0.7.29.zip"
entries = [line.split() for line in Path("SHA256SUMS").read_text().splitlines() if line.strip()]
matches = [parts[0] for parts in entries if len(parts) == 2 and parts[1] == name]
if len(matches) != 1:
    raise SystemExit("Missing or duplicate checksum entry")
if hashlib.sha256(Path(name).read_bytes()).hexdigest() != matches[0]:
    raise SystemExit("Checksum mismatch: do not install")
print("Verified", name)
```

Checksums detect changed bytes; they are not an independent publisher signature.

## Install and configure — inside Kodi on the TV

1. Open **Settings → System → Add-ons** and enable **Unknown sources** if needed. If the option is
   hidden, select the Standard/Expert settings level.
2. Go to **Add-ons → Install from zip file** and select the transferred ZIP. Use Kodi's native
   installer; do not copy an unpacked add-on behind Kodi's database.
3. Open **My add-ons → Services → Kodi Manager → Configure**.
4. To open the dashboard from another device, turn on **Allow LAN access** (under **Dashboard**). The
   default port is `8765`; without LAN access the service only listens on the Kodi device itself.
   Leave **Enable writes** off for first setup. Changes to these settings apply straight away; there
   is no need to restart Kodi.

An authorized agent can perform TV navigation through its supported tools where available. The
native installation and service permissions still need to be applied inside Kodi.

## Connect — on the TV

In Kodi, open **Add-ons → Video add-ons → Kodi Manager → Open the dashboard on another device**.
It shows the dashboard address and access token, or tells you to turn on LAN access first. Open
that address in a browser on the same network and enter the token when asked.
Use `http://` as shown, not `https://`. The token belongs to the active Kodi profile; switching
profiles can require signing in again with that profile's token.

Once signed in, **Advanced → Connection** offers a **Copy sign-in link** button. The link has the form
`http://KODI_IP:8765/#token=…`: opening it on your phone or another computer signs that browser in.
The fragment after `#` is omitted from the initial HTTP URL; the dashboard consumes it, removes it
from the address bar and sends the token in the `Authorization: Bearer` header for API requests.
It saves the token in that browser's local storage; use **Forget token in this browser** on a shared
device. Treat the sign-in link like a password.

## Connect and verify — agent/computer

1. Privately read `auth_token` from the **active profile's**
   `addon_data/service.kodi.addonadmin/settings.xml` through local/mounted/authorized ADB storage.
   Parse it in a local process without printing it into tool output. It is separate from Kodi's HTTP
   username/password. A library install or HTTP password does not generate this token.
   If storage is inaccessible, use the full token displayed by **Video add-ons → Kodi Manager →
   Open the dashboard on another device** and private input; the settings field may be masked.
2. Open `http://YOUR_KODI_IP:8765` using the actual IP/port. Enter the generated token in the
   dashboard's sign-in form, privately. Do not share a filled config, token-bearing URL or
   diagnostics. A manual installer can read and enter the same token through private local access.
3. Verify `/api/status`, `/api/overview` (active profile), `/api/addons` and `/api/pipeline` with
   the bearer token. Start with read-only
   requests; provider folder previews execute installed add-on code and can make network requests.
4. For nvidia-MCP, merge `KODI_MANAGER_TOKEN` and `KODI_MANAGER_PORT` into the client's private
   environment, preserve other servers and reload the connection. Follow
   [companion setup](https://github.com/glasgowm148/nvidia-MCP/blob/main/docs/companion.md).

Use this bearer-authenticated HTTP service only on a trusted LAN or a user-managed secure tunnel.
It has no transport encryption. Do not expose it to the internet. Backups/account/log diagnostics
can contain credentials; keep them private.

## Connection troubleshooting

| Symptom | Check |
| --- | --- |
| Browser cannot connect | Kodi and the service are running; the device's current IP and port; **Allow LAN access** is on |
| Works on the Kodi device only | **Allow LAN access** is off |
| Authentication error | Active-profile `auth_token`, not Kodi HTTP credentials or another profile's token |
| `host_not_allowed` (403) | Open the dashboard by IP address (`http://192.168.x.y:8765`), a `.local` name or `localhost`; other host names are refused as a DNS-rebinding defence |
| Connected but changes disabled | **Enable writes** in the add-on settings; Python/MCP clients have their own write opt-in too |
| Home layout missing or view-only | It appears only for reviewed skin and Skin Shortcuts versions **and source hashes** |
| Provider preview empty/fails | Provider enabled, accounts configured and route available; see provider logs |
| Agent cannot read Kodi files | Android scoped storage may block ADB; use an available mounted/local route |

The general dashboard works across skins. Add-on settings need a supported schema/adapter, editing
needs an allowed add-on, and cached rows need a supported listing route and compatible skin picker. The Home layout
editor currently recognises reviewed **Bingie 2.0.2 / Skin Shortcuts 2.0.3** sources; other skins and
unknown forks do not get it.
For backups/restores and safe upgrades, see [recovery](recovery.md). For clients, see [API](api.md).
For download mistakes, network isolation, missing features and updates, see
[troubleshooting](troubleshooting.md).

## Android TV and Fire TV

The same service ZIP runs inside official Kodi 19+ on Android TV, Google TV and Android-based
**Fire OS**. It uses Kodi’s public Python API and resolved `special://` storage paths; there is no
NVIDIA-specific connector. The dashboard alone does not require ADB or Kodi HTTP control.

Check [Amazon’s device/OS table](https://developer.amazon.com/docs/fire-tv/fire-os-overview.html):
**Vega OS** Firesticks use different tooling and are outside this Android support. No Vega port
or live Firestick/Google TV validation is claimed. [Compatibility](compatibility.md) separates
protocol/fixture evidence from the single Shield used live.

For agent file transfer, follow nvidia-MCP’s [Android TV / Fire OS guide](https://github.com/glasgowm148/nvidia-MCP/blob/main/docs/android-tv.md).
A Fire OS network-debugging port is normally 5555; Google TV Wireless debugging can require a
six-digit code and different pairing/connection ports. The Manager token, Kodi HTTP credentials
and temporary ADB pairing code are separate. Install ZIPs through Kodi’s native installer even
when Android restricts direct access to `Android/data`. If needed, transfer to Download and select
that folder in Kodi instead; do not bypass Android permissions.

On lower-memory boxes/sticks, start with a few cached rows/pages and manual refresh. The cache
still runs providers during refresh, so it cannot remove their CPU/network cost. Performance on
these devices is unverified. The opt-in Shield exit workaround checks NVIDIA’s driver and stays
disabled on Fire OS and generic Android boxes, including when that option was copied from a Shield.
