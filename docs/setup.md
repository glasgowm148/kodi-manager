# Install Kodi Manager

Kodi Manager has a TV service, browser dashboard and computer-side Python library.
For the dashboard, all you need is Kodi and a browser. Install the service ZIP inside Kodi.
Installing the library on your computer alone does not install or start the TV service.

The instructions below use release 0.7.31, marked prerelease; check [Releases](https://github.com/glasgowm148/kodi-manager/releases) for newer service ZIPs. See [compatibility](compatibility.md)
for remaining live checks. Back up an existing customized installation before upgrading: public
releases deliberately omit household settings and separate third-party patch bundles.

For Apple TV, follow [tvOS installation and recovery](apple-tv.md). Install from a Kodi-readable network source, enable LAN access, enter the token privately and keep Kodi active. Android transfer/forwarding instructions below do not apply.

## Before you start on the TV

1. Open Kodi on the device you want to manage. The TV and computer should be on the same home network.
2. Find its local IPv4 address. On a Shield: Home -> Settings gear -> Device Preferences -> About ->
   Status -> IP address. Older firmware may put About directly under Settings. On Fire OS use Settings -> My Fire TV ->
   About -> Network; on Google TV use the connected Network & Internet entry or About/Status.
3. If an agent will transfer files or read the token through ADB, enable the device’s Network
   debugging, ADB Debugging (Fire OS), or paired Wireless debugging (Google TV).
   Follow [Android TV / Fire TV preparation](https://github.com/glasgowm148/nvidia-MCP/blob/main/docs/android-tv.md)
   for device-specific menus and pairing/connection ports. Approve the debugging prompt
   when the agent connects. A mounted/local Kodi storage path is another option.
4. Confirm viewing has finished before TV navigation, installation or restarting Kodi.

Kodi's separate HTTP control service is needed for nvidia-MCP's Kodi RPC tools, but is not required
for the Manager dashboard alone.

## Download and transfer the ZIP

On your computer or phone, open [Releases](https://github.com/glasgowm148/kodi-manager/releases)
and expand Assets on the newest release, including prereleases. Download
`service.kodi.addonadmin-<version>.zip` and `SHA256SUMS`. The Source code ZIP, wheel and tar.gz
are not installable Kodi add-ons. See [checksum verification](#verify-the-download).

Put the ZIP somewhere Kodi can browse, such as local Downloads, a supported USB drive or a
private network share. Transfer methods depend on your device; see [Android/Fire TV](#android-tv-and-fire-tv)
or [Apple TV](apple-tv.md). You do not need an assistant or ADB if you can transfer the file yourself.

## Install and configure inside Kodi

1. Open Settings -> System -> Add-ons and enable Unknown sources if needed. If the option is
   hidden, select the Standard/Expert settings level.
2. Go to Add-ons -> Install from zip file and select the transferred ZIP. Use Kodi's native
   installer; do not copy an unpacked add-on behind Kodi's database.
3. Open Settings -> Add-ons -> My add-ons -> Services -> Kodi Manager -> Configure.
4. To open the dashboard from another device, turn on Allow LAN access (under Dashboard). The
   default port is `8765`; without LAN access the service only listens on the Kodi device itself.
   Leave Enable writes off for first setup. Select OK to save the settings. Changes apply
   without restarting Kodi.

An authorized agent can perform TV navigation through its supported tools where available. The
native installation and service permissions still need to be applied inside Kodi.

<a id="connect--on-the-tv"></a>

## Find the token and sign in

1. Back out to Kodi's home screen. Open Add-ons -> Video add-ons and select the Kodi Manager
   tile directly, rather than opening its information or configuration screen through My add-ons.
   The exact location can vary with your skin.
2. In Kodi Manager's menu, select “Open the dashboard on another device”. It displays the address
   and full access token, or asks you to enable LAN access first. It does not launch a browser on
   the TV and is not a switch in Configure.
3. Open that address on your phone or computer on the same network. The default is
   `http://YOUR_KODI_IP:8765`. Use your device's actual IP and configured port, with `http://`, not `https://`.
4. Enter the displayed token in the browser's access-token field and sign in. This token is
   separate from Kodi's HTTP password, Trakt and debrid credentials. Keep Kodi running.

Reaching the browser login page confirms the service is reachable. You do not need to enable
another dashboard setting before signing in. If you cannot find the token, use the fallback below.

### Only Configure is available

Kodi Manager includes both a background service and a video plugin. In My add-ons, its information
screen can show Configure with no usable Open button. That screen is not the plugin's menu.
First try the home-screen route above. If that still fails, use the fallback below and report your setup details.

If the tile is absent or still will not open, you can sign in through settings alone:

1. Open Settings -> Add-ons -> My add-ons -> Services -> Kodi Manager -> Configure -> Dashboard.
2. Select Auth token. The existing value is masked. Replace it with your own private random
   token, preferably generated by a password manager with at least 32 letters and digits.
   Keep a private copy to enter on your phone/computer. Do not use an example from documentation.
3. Keep Allow LAN access on, leave Enable writes off, and select OK to save.
4. Open `http://YOUR_KODI_IP:8765` (or your configured port) in the browser and sign in with
   exactly the token you just saved. No Kodi restart is required for this setting change.

Changing Auth token invalidates the old token for this profile. Existing browser and MCP clients
must use the replacement. Leaving it blank generates a new token whose value you will still need
to retrieve, so blanking it is not a workaround for an inaccessible token display.

If this still fails, report Kodi Manager version, Kodi version, skin, device, exact menu route and
what happens. A screenshot of the Configure/information screen can help, but exclude the token
and account details.

### Profiles, web editing and additional browsers

The token, LAN access and Enable writes belong to the active Kodi profile. Switching profiles
can require signing in again with that profile's token. Enable writes controls changes through
the web dashboard; “View only” does not stop changes through Kodi's own controls.

Once signed in, Advanced -> Connection offers Copy sign-in link. The link has the form
`http://KODI_IP:8765/#token=…`: opening it on another device signs that browser in. The fragment
is omitted from the initial HTTP request; the dashboard consumes it, removes it from the address
bar and sends the token in the Authorization header. It saves the token in that browser's local
storage. Use Forget token in this browser on a shared device, and treat sign-in links like passwords.

## Let an AI agent handle the computer side

This section is optional. Manual setup above does not require an assistant.

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

## Prepare the release for an agent

An agent with terminal/file access should perform these steps rather than handing the user commands
or JSON editing tasks. Ask only for missing connection information or unavoidable TV actions.

1. Check for an existing Manager installation and inspect its version/profile before replacing it.
   Preserve local changes and create an appropriate private backup for an authorized upgrade.
2. Download `service.kodi.addonadmin-0.7.31.zip` and `SHA256SUMS` from the release's Assets at
   [v0.7.31](https://github.com/glasgowm148/kodi-manager/releases/tag/v0.7.31). Verify the ZIP checksum.
   GitHub's Source code ZIP, Python wheel and tar.gz cannot be installed through Kodi.
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

name = "service.kodi.addonadmin-0.7.31.zip"
entries = [line.split() for line in Path("SHA256SUMS").read_text().splitlines() if line.strip()]
matches = [parts[0] for parts in entries if len(parts) == 2 and parts[1] == name]
if len(matches) != 1:
    raise SystemExit("Missing or duplicate checksum entry")
if hashlib.sha256(Path(name).read_bytes()).hexdigest() != matches[0]:
    raise SystemExit("Checksum mismatch: do not install")
print("Verified", name)
```

Checksums detect changed bytes; they are not an independent publisher signature.

## Connect and verify from an agent/computer

1. Privately read `auth_token` from the active profile's
   `addon_data/service.kodi.addonadmin/settings.xml` through local/mounted/authorized ADB storage.
   Parse it in a local process without printing it into tool output. It is separate from Kodi's HTTP
   username/password. A library install or HTTP password does not generate this token.
   If storage is inaccessible, use the full token displayed by Video add-ons -> Kodi Manager ->
   Open the dashboard on another device and private input; the settings field may be masked.
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
| Browser cannot connect | Kodi and the service are running; the device's current IP and port; Allow LAN access is on |
| Works on the Kodi device only | Allow LAN access is off |
| Only Configure is available | Follow [the token/setup fallback](#only-configure-is-available); the browser login page already confirms reachability |
| Authentication error | Active-profile `auth_token`, not Kodi HTTP credentials or another profile's token |
| `host_not_allowed` (403) | Open the dashboard by IP address (`http://192.168.x.y:8765`), a `.local` name or `localhost`; other host names are refused as a DNS-rebinding defence |
| Connected but changes disabled | Enable writes in the add-on settings; Python/MCP clients have their own write opt-in too |
| Home layout missing or view-only | It appears only for reviewed skin and Skin Shortcuts versions and source hashes |
| Provider preview empty/fails | Provider enabled, accounts configured and route available; see provider logs |
| Agent cannot read Kodi files | Android scoped storage may block ADB; use an available mounted/local route |

The general dashboard works across skins. Add-on settings need a supported schema/adapter, editing
needs an allowed add-on, and cached rows need a supported listing route and compatible skin picker. The Home layout
editor currently recognises reviewed Bingie 2.0.2 / Skin Shortcuts 2.0.3 sources; other skins and
unknown forks do not get it.
For backups/restores and safe upgrades, see [recovery](recovery.md). For clients, see [API](api.md).
For download mistakes, network isolation, missing features and updates, see
[troubleshooting](troubleshooting.md).

## Android TV and Fire TV

The same service ZIP runs inside official Kodi 19+ on Android TV, Google TV and Android-based
Fire OS. It uses Kodi’s public Python API and resolved `special://` storage paths; there is no
NVIDIA-specific connector. The dashboard alone does not require ADB or Kodi HTTP control.

Check [Amazon’s device/OS table](https://developer.amazon.com/docs/fire-tv/fire-os-overview.html):
Vega OS Firesticks use different tooling and are outside this Android support. No Vega port
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
