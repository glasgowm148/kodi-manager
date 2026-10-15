# Agent setup and manual ZIP installation

For computer agents and advanced/manual installations. Most users should follow the
[repository setup guide](setup.md); it does not need ADB or file transfer.

## Manual ZIP installation

Use a standalone ZIP for offline installation, a pinned version or an exported nvidia-MCP bundle.
Download `service.kodi.addonadmin-<version>.zip` and `SHA256SUMS` from
[Releases](https://github.com/glasgowm148/kodi-manager/releases). Choose the service ZIP,
not Source code, a wheel or tar.gz. Verify it as described below.

Put it on local storage, a supported USB drive or a private network share Kodi can browse.
In Kodi, enable Settings → System → Add-ons → Unknown sources, then select
Add-ons → Install from zip file and choose the ZIP. Use Kodi’s installer rather than
copying an unpacked add-on folder. Continue with [dashboard setup](setup.md#3-enable-dashboard-access).

Standalone ZIP installs have manual updates unless you also install the repository and select
Kodi Manager from it. A pinned/offline installation should keep automatic updates off for that add-on.

## Let an AI agent handle the computer side

This section is optional. Manual setup above does not require an assistant.

You handle the TV and Kodi's installer; the agent downloads, verifies and transfers the ZIP and
connects to the dashboard. If using ADB for transfer on Android TV or Fire OS, complete the
[device debugging preparation](https://github.com/glasgowm148/nvidia-MCP/blob/main/docs/android-tv.md) first.
Manual installation or transfer through a Kodi-readable share does not require ADB or nvidia-MCP.

```text
Set up https://github.com/glasgowm148/kodi-manager for my Kodi device.
Read docs/setup-agent.md and handle this manual ZIP installation.
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
2. Download `service.kodi.addonadmin-0.7.38.zip` and `SHA256SUMS` from the release's Assets at
   [v0.7.38](https://github.com/glasgowm148/kodi-manager/releases/tag/v0.7.38). Verify the ZIP checksum.
   GitHub's Source code ZIP, Python wheel and tar.gz cannot be installed through Kodi.
   nvidia-MCP users can instead export its pinned older bundle (currently 0.7.23) with
   `nvidia-mcp --export-manager DIRECTORY`. That command checks the ZIP itself and creates no
   `SHA256SUMS`, so skip the check below. Never install it over a newer Manager.
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

name = "service.kodi.addonadmin-0.7.38.zip"
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

Use this bearer-authenticated HTTP service only on a trusted LAN. Remote clients need private or
loopback addresses: an SSH local port forward to `localhost`, or a VPN using private (RFC 1918) or
IPv6 ULA addresses. 100.64.0.0/10 VPN addresses, such as Tailscale's IPv4 addresses, are refused.
It has no transport encryption. Do not expose it to the internet. Backups/account/log diagnostics
can contain credentials; keep them private.

