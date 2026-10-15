<p align="center">
  <img src="docs/images/banner.svg" alt="Kodi Manager : Understand your setup. Shape your Kodi experience." width="100%">
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
  <a href="#documentation">Documentation</a>
</p>

Inspect and configure Kodi from your browser. Kodi Manager is an add-on with a local dashboard
for status, add-on settings, playback routing, backups and home-screen rows. Use it from a phone or
computer, on its own or with [nvidia-MCP](https://github.com/glasgowm148/nvidia-MCP).

![Kodi Manager overview: clickable status charts, recorded log activity and management shortcuts](docs/images/dashboard.png)

*Captured with synthetic demo data. No personal accounts, watch history or TV screenshots are included.*

> [!NOTE]
> Preview software. Targets Kodi 19+; cached rows need Kodi 20+. Live use is on one customized
> NVIDIA Shield. The current public ZIP and other hardware still need live validation;
> see [compatibility](docs/compatibility.md).

## What you can do

- Start with current issues and direct tasks for add-ons, home rows, playback, accounts and recovery.
- Inspect playback, memory, connection checks, account status and seven-day trends.
- Understand add-on purposes and dependencies, then edit supported settings with backups.
- Keep masked 24-hour logs across restarts, with grouped issues, explanations and recurrence after review.
- Trace the playback pipeline from skin and metadata helper to selected player.
- Create configuration checkpoints, restore them and undo restores.
- Serve optional [cached home-screen rows](docs/widget-cache.md).
- Preview and apply home layouts for reviewed Bingie / Skin Shortcuts sources.

<details>
<summary><strong>See the playback pipeline</strong></summary>

![Playback pipeline showing the interface, metadata helper, playback provider and routing evidence](docs/images/pipeline.png)

*Synthetic example: Bingie -> TMDb Bingie Helper -> POV. Detected relationships are separate from account authentication.*

</details>

## Quick start

You need Kodi and a browser on the same trusted home network. No AI agent, MCP, ADB or
Python installation on your computer is needed for the dashboard.

1. In **Kodi → Settings → File manager → Add source**, enter
   `https://glasgowm148.github.io/kodi-manager/` and name it **Kodi Manager**.
2. Enable **Settings → System → Add-ons → Unknown sources**. Open **Add-ons → the open-box icon →
   Install from zip file → Kodi Manager → repository.kodi-manager.zip**. Wait for the repository-installed notice.
3. Select **Install from repository → Kodi Manager Repository (preview) → Services → Kodi Manager → Install**.
4. Open **Settings → Add-ons → My add-ons → Services → Kodi Manager → Configure → Dashboard**.
   Turn on **Allow LAN access**, leave **Enable writes** off, then select **OK**.
5. Return to Kodi's home screen. Open **Add-ons → Video add-ons → Kodi Manager →
   Open the dashboard on another device**. The TV shows an address and access token.
6. Open that address on your phone or computer, enter the token and sign in. Keep Kodi running.

**[Full remote-control steps, including Firestick / Android TV](docs/setup.md).**
The repository supplies preview releases; updates follow Kodi's update settings.
No file transfer or ADB debugging is needed. [Manual/offline ZIP installation](docs/setup-agent.md) is also available.

Only seeing Configure, or an unavailable Open button? The My add-ons information screen is
separate from the home-screen video add-on menu. Follow
[the token/setup fallback](docs/setup.md#only-configure-is-available) if the tile still will not open.
If your browser already shows the login page, the service is reachable; you need its access token next.

To edit settings from the dashboard, enable Enable writes in Kodi Manager's settings for the
active Kodi profile. “View only” means web editing is off for that profile; it does not mean
installation failed.

[Full setup guide](docs/setup.md) · [Troubleshooting](docs/troubleshooting.md).
Keep access on a trusted LAN. Tokens travel over plain HTTP; sign-in links, settings and backups
can contain credentials and must stay private.

## Questions

| Question | Answer |
| --- | --- |
| Do I need an AI agent or ADB? | The dashboard needs only Kodi and a browser. Both are optional for setup or automation. |
| Android boxes / Firestick? | Targets Android TV, Google TV and Android-based Fire OS. Physical validation is pending; Vega OS is unsupported. [Device guide](docs/setup.md#android-tv-and-fire-tv) |
| Apple TV? | Experimental dashboard, settings, widgets and reviewed skin workflows while Kodi is active. Physical validation is pending. [tvOS guide](docs/apple-tv.md) |
| Any skin or add-on? | General inspection works across skins; editing depends on the setting adapter and allowed add-ons. Home layout writes require reviewed source hashes. [FAQ](docs/faq.md) |

See the [FAQ](docs/faq.md) for write behavior, profile tokens, removal and support limits;
[troubleshooting](docs/troubleshooting.md) covers installation and connection failures.

<a id="optional-faster-home-screen-rows"></a>
Optional row caching, its measured results and undo steps are in the [widget cache guide](docs/widget-cache.md).

## For developers

The dependency-free Python 3.9+ library exposes `ManagerClient`, `parse_schema` and
`flatten_settings`. See the [library guide](docs/library.md) for installation and examples, the
[HTTP API](docs/api.md) for endpoints, and [Contributing](CONTRIBUTING.md) for tests and release checks.
Installing the library alone does not install the Kodi service.

## Documentation

The [documentation index](docs/README.md) covers all guides.

| I want to… | Guide |
| --- | --- |
| Install and sign in | [Setup](docs/setup.md) · [Troubleshooting](docs/troubleshooting.md) |
| Check device or skin support | [Compatibility](docs/compatibility.md) · [Apple TV](docs/apple-tv.md) |
| Configure home-screen rows | [Widget cache](docs/widget-cache.md) |
| Recover or upgrade | [Backups and recovery](docs/recovery.md) |
| Build an integration | [Python library](docs/library.md) · [HTTP API](docs/api.md) · [Private extensions](docs/extensions.md) |

[Contributing](CONTRIBUTING.md) · [Changelog](CHANGELOG.md) · [Security](SECURITY.md) · [MIT license](LICENSE).
Independent project; not affiliated with the Kodi Foundation, NVIDIA or any add-on author.
You supply your own add-ons and accounts.
