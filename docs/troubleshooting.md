# First-run troubleshooting

Kodi Manager runs inside Kodi. Its browser dashboard needs no AI subscription or computer-side
Python installation. Use the [setup guide](setup.md) first; nvidia-MCP is optional.

| Symptom | Likely cause and next step |
| --- | --- |
| Kodi says the ZIP has an invalid structure or dependencies fail | Under release **Assets**, select `service.kodi.addonadmin-0.7.14.zip`, not **Source code**, a wheel or tar.gz. Kodi 19+ is required. Enable Unknown sources if Kodi asks. |
| No dashboard opens from the TV | Use **Video add-ons → Kodi Manager → Open the dashboard on another device**. This shows an address/token for your phone or computer; it is not a TV browser. |
| Browser cannot connect | Keep Kodi open, check the device's current IP/port and turn on **Allow LAN access** in Manager's service settings. Use the displayed `http://` address; the service does not provide HTTPS. |
| Same Wi-Fi name, but no connection | Guest Wi-Fi/client isolation can block devices from each other. Use a network that permits LAN access. Check VPN LAN settings, firewall rules and the browser/app's OS Local Network permission. Ethernet and Wi-Fi can work together on the same LAN. |
| Sign-in fails | Use Manager's access token, not the Kodi HTTP password, a Trakt/debrid token or the example token in documentation. Copy the current token from the TV entry above. |
| Signed out after changing Kodi profiles | Each profile can have a different token, write mode, settings and rows. Use the active profile's token; Manager manages that profile, rather than switching profiles remotely. |
| A custom host name returns 403 | Open by IP address, `.local` name or localhost. Other names are refused to protect the local service. |
| Settings are greyed out, or an add-on refuses editing | Turn on **Enable writes** for the active profile. Add-ons outside the detected setup need an explicit entry in **Also allow editing these add-ons**. MCP/Python clients also have their own write opt-in. |
| There is no Home layout page | The editor needs reviewed Bingie 2.0.2 / Skin Shortcuts 2.0.3 versions and source hashes. Other skins and changed forks retain the dashboard/settings/cache features. See [compatibility](compatibility.md). |
| Cached rows do not change the home screen | Creating a cache does not replace a skin's existing widget. Select a Kodi Manager cached row as that widget's source using your skin's native settings. Kodi 20+ and an installed, configured provider are required; see [cached rows](widget-cache.md). |
| A row is empty or an account is “unknown” | Confirm the provider works in Kodi and has the required sign-in. Installed/configured does not prove authenticated. Provider APIs can fail or legitimately return no items. Inspect a bounded preview/log before rebuilding rows. |
| A request times out | Kodi may still be working, especially on a change. Inspect the current setting/row/backup before trying again. Manager never automatically repeats a timed-out change. |
| Old-looking dashboard after an upgrade | Reload the browser. Confirm **Connection** shows the expected service version; Kodi may need restarting after installation, when viewing has finished. Settings changes themselves apply without a restart. |

Updates are manual: download the new **service ZIP**, verify its checksum and install it through
Kodi's native installer. These GitHub releases do not register an auto-updating Kodi repository.
Back up a customized installation first; see [recovery](recovery.md).

If it still fails, [open an issue](https://github.com/glasgowm148/kodi-manager/issues/new/choose) with
Manager/Kodi/skin versions, device and browser, read/write mode, brief steps and the error code.
Include only a few inspected, redacted log lines. Never attach tokens, sign-in links, backups,
settings exports, raw logs or account/history data. A log redactor helps but does not replace review.
