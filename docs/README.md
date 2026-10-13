# Kodi Manager documentation

The service runs inside Kodi and serves the dashboard/API. Its Python library runs separately on
computers; installing that library does not install the service.

## Start here

1. [Setup](setup.md): choose the installable ZIP, install in Kodi, enable LAN access and sign in.
   Only Configure is available? Use the [token/setup fallback](setup.md#only-configure-is-available).
2. [FAQ](faq.md): skins, devices, write behavior, privacy and removal.
3. [Troubleshooting](troubleshooting.md): installation, network, tokens and missing features.

[Compatibility](compatibility.md) separates live Shield use from automated tests.
Apple TV support is experimental: read [tvOS setup and recovery limits](apple-tv.md).

## Use the dashboard

| Guide | Contents |
| --- | --- |
| [Dashboard guide](ui.md) | Navigation, overview, trends, row health and diagnostic pages |
| [Cached rows](widget-cache.md) | Add rows, refresh, performance evidence, limits and undo |
| [Backups and recovery](recovery.md) | Checkpoints, restore, undo, retention and upgrade precautions |

## Develop and contribute

| Guide | Contents |
| --- | --- |
| [Python library](library.md) | Install, connect and parse settings offline |
| [HTTP API](api.md) | Authentication, endpoint contracts, preview/apply and refusal codes |
| [Private extensions](extensions.md) | Add private behavior without maintaining a second core source tree |
| [Contributing](../CONTRIBUTING.md) | Python, UI, type, build and release checks |
| [Browser tests](../e2e/README.md) | Synthetic fixtures and platform-specific screenshot baselines |

[Changelog](../CHANGELOG.md) · [Security and private reports](../SECURITY.md) · [Back to the project](../README.md).
