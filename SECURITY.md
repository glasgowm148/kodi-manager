# Security and recovery

Loopback-only binding and disabled write mode are the portable defaults. LAN mode requires a generated
bearer token. No credentials, installer seeds, private logs, device fixes or backups are distributed.
Do not forward the service port to the internet. HTTP bearer tokens and dashboard local storage require
a trusted local network/browser. The Python client refuses redirects and environment proxies.

Kodi runs installed provider code with the user's permissions. Authenticated service write access can
edit settings, restore configuration, install a user-specified local ZIP and open Kodi windows. It is a
management capability, not a sandbox. Enable writes deliberately and keep tokens/backups private.
Backups, logs and account diagnostics may contain personal data. Report findings with synthetic
reproduction steps and redacted output via a private GitHub security advisory; never include real
tokens or an entire Kodi backup in an issue.

The fix protection engine accepts externally supplied verified manifests for reviewed code versions.
No third-party patch payloads ship here. Unknown Bingie sources cannot be written by the layout
adapter. Back up an existing customized Manager before installing this portable companion.
