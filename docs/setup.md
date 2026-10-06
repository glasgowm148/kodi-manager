# Install Kodi Manager

Kodi Manager has a **TV service**, **browser dashboard** and **computer-side Python library**.
For live settings/dashboard access, install the service ZIP inside Kodi. Installing the library on
your computer alone does not install or start the TV service.

The current portable release is **0.6.2**, marked prerelease. See [compatibility](compatibility.md)
for remaining live checks. Back up an existing customized installation before upgrading: public
releases deliberately omit household settings and separate third-party patch bundles.

## Before you start — on the TV

1. Open Kodi on the device you want to manage. The TV and computer should be on the same home network.
2. Find its local IPv4 address. On a Shield: **Home → Settings gear → Device Preferences → About →
   Status → IP address**. Older firmware may put About directly under Settings.
3. If an agent will transfer files or read the token through ADB, enable **Network debugging**.
   Follow [Shield TV preparation](https://github.com/glasgowm148/nvidia-MCP/blob/main/docs/setup.md)
   for the seven presses on Build and exact developer-options menus. Approve the debugging prompt
   when the agent connects. A mounted/local Kodi storage path is another option.
4. Confirm viewing has finished before TV navigation, installation or restarting Kodi.

Kodi's separate HTTP control service is needed for nvidia-MCP's Kodi RPC tools, but is not required
for the Manager dashboard alone.

## Prepare the release — agent/computer

An agent with terminal/file access should perform these steps rather than handing the user commands
or JSON editing tasks. Ask only for missing connection information or unavoidable TV actions.

1. Check for an existing Manager installation and inspect its version/profile before replacing it.
   Preserve local changes and create an appropriate private backup for an authorized upgrade.
2. Download `service.kodi.addonadmin-0.6.2.zip` and `SHA256SUMS` from the
   [release](https://github.com/glasgowm148/kodi-manager/releases/tag/v0.6.2). Verify the ZIP checksum.
   nvidia-MCP users can instead export the pinned bundle with `nvidia-mcp --export-manager DIRECTORY`.
3. Transfer the verified ZIP to a Kodi-accessible folder using authorized ADB, a mounted share or
   local storage. Use only the configured device, not a LAN scan. Give the user the exact folder and
   file name to select. If no transfer route is available, explain the specific manual copy needed.

## Install and configure — inside Kodi on the TV

1. Open **Settings → System → Add-ons** and enable **Unknown sources** if needed. If the option is
   hidden, select the Standard/Expert settings level.
2. Go to **Add-ons → Install from zip file** and select the transferred ZIP. Use Kodi's native
   installer; do not copy an unpacked add-on behind Kodi's database.
3. Open **My add-ons → Services → Kodi Manager → Configure**.
4. To access it from another computer, enable **LAN access**, set the bind host to `0.0.0.0` and
   port to `8765`. The default is loopback-only. Leave **Write mode** disabled for first setup.
5. Restart the service/Kodi when the TV is free and interruption is authorized.

An authorized agent can perform TV navigation through its supported tools where available. The
native installation and service permissions still need to be applied inside Kodi.

## Connect — on the TV

In Kodi, open **Add-ons → Video add-ons → Kodi Manager → Open the dashboard on another device**.
It shows the dashboard address and access token, or tells you to turn on LAN access first. Open
that address in a browser on the same network and enter the token when asked.

## Connect and verify — agent/computer

1. Privately read `auth_token` from the **active profile's**
   `addon_data/service.kodi.addonadmin/settings.xml` through local/mounted/authorized ADB storage.
   Parse it in a local process without printing it into tool output. It is separate from Kodi's HTTP
   username/password. A library install or HTTP password does not generate this token.
2. Open `http://YOUR_KODI_IP:8765` using the actual IP/port. Enter the generated token in the
   dashboard's authentication prompt, privately. Do not share a filled config, token-bearing URL or
   diagnostics. A manual installer can read and enter the same token through private local access.
3. Verify `/api/status`, installed add-ons, the active profile and pipeline. Start with read-only
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
| Browser cannot connect | Kodi/service running, current device IP, port, LAN access and host `0.0.0.0` |
| Works on the Kodi device only | Loopback binding; enable LAN access and restart when free |
| Authentication error | Active-profile `auth_token`, not Kodi HTTP credentials or another profile's token |
| Connected but changes disabled | Service Write mode; Python/MCP clients have their own write opt-in too |
| Bingie layout is view-only | Reviewed skin/Shortcuts versions **and source hashes** are required |
| Provider preview empty/fails | Provider enabled, accounts configured and route available; see provider logs |
| Agent cannot read Kodi files | Android scoped storage may block ADB; use an available mounted/local route |

Generic settings/discovery do not require Bingie. Layout writes currently recognize reviewed
**Bingie 2.0.2 / Skin Shortcuts 2.0.3** sources; unknown forks remain view-only.
For backups/restores and safe upgrades, see [recovery](recovery.md). For clients, see [API](api.md).
