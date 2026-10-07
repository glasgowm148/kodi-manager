# Security and recovery

Loopback-only binding and **Enable writes** off are the defaults. Turning on **Allow LAN access** makes
the service listen on the local network and refuse non-private addresses. Every API request needs the
generated bearer token. No credentials, installer seeds, private logs, device fixes or backups are distributed.
Do not forward the service port to the internet. HTTP bearer tokens and dashboard local storage require
a trusted local network/browser. The dashboard reads a sign-in token only from the URL fragment
(`#token=`), which browsers never send to the server, and removes it from the address bar. It has no
inline scripts or event handlers and sets a `script-src 'self'` content security policy. The Python
client refuses redirects and environment proxies.

Kodi runs installed provider code with the user's permissions. Authenticated service write access can
edit settings, restore configuration, open Kodi windows and open Kodi's own Install from zip file
dialog on the TV (the person at the TV still picks the ZIP and Kodi applies its unknown-sources check). It is a
management capability, not a sandbox. Enable writes deliberately and keep tokens/backups private.
Backups, logs and account diagnostics may contain personal data. Report findings with synthetic
reproduction steps and redacted output via a private GitHub security advisory; never include real
tokens or an entire Kodi backup in an issue.

Use [GitHub's private vulnerability reporting](https://github.com/glasgowm148/kodi-manager/security/advisories/new).
Include affected versions and a minimal synthetic reproduction; avoid public exploit reports while a
fix is being coordinated. The portable service remains a prerelease with [documented verification limits](docs/compatibility.md).

The fix protection engine accepts externally supplied verified manifests for reviewed code versions.
No third-party patch payloads ship here. Skin sources whose version and hash have not been reviewed
are view-only in the layout editor. Back up an existing customized Manager before installing this portable companion.
