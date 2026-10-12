# Frequently asked questions

## Do I need a particular skin or add-on?

General inspection works across skins. Settings depend on the add-on's supported schema/adapter;
editing is limited to the detected stack or add-ons you explicitly allow in Manager's settings.
Cached rows require a supported read-only listing route and a skin that can display it.
The Home layout editor requires reviewed Bingie / Skin Shortcuts versions and source hashes.
See [setup](setup.md) and [API access rules](api.md).

## Does it change anything by itself?

**Enable writes** starts off. Settings and layout edits require that opt-in and make backups;
installs and menu rebuilds refuse while playing. The service still collects idle health/history data
and can run scheduled configuration checkpoints. The optional cache refreshes provider listings
in the background; automatic row routing has its own opt-in. See [cached rows](widget-cache.md)
and [recovery](recovery.md) for schedules, retention and undo.

## Android boxes and Firestick?

Yes, the service targets Kodi 19+ on Android TV, Google TV and Android-based Fire OS using Kodi’s
public Python API. ADB is optional for transferring files; the dashboard needs only a browser.
Check [Amazon’s OS table](https://developer.amazon.com/docs/fire-tv/fire-os-overview.html): Vega OS
Firesticks are outside this Android support. Fire OS/Google TV hardware testing is still pending;
see [device setup and limits](setup.md#android-tv-and-fire-tv).

## Apple TV?

Experimental support is included from 0.7.16: the dashboard and reviewed skin,
settings, widget and backup workflows use Kodi's tvOS virtual XML storage. Kodi must be active;
unknown native focus blocks actions. Use direct LAN HTTP and install the ZIP through Kodi from
a readable network source. No physical Apple TV validation yet; tvOS caches and backup manifests
can be purged. See [Apple TV setup and recovery limits](apple-tv.md).

## Which Kodi versions?

Kodi 19 or newer; the optional row cache needs Kodi 20. Live use covers one Shield on Kodi 22 beta 2
and RC1; see
[compatibility](compatibility.md).

## Is it safe on my network?

Keep it on your home network. The dashboard uses an access token over plain HTTP, so don't expose it
to the internet. Backups and diagnostics can contain credentials. Releases contain Kodi Manager's
code only: no accounts, watch history or third-party add-on patches.

## How do I remove it?

Uninstall it from **Add-ons → My add-ons → Services**. If you used cached rows, switch those rows
back first; the [widget cache guide](widget-cache.md#manage-and-undo) explains how.

For installation and connection errors, use [troubleshooting](troubleshooting.md).
