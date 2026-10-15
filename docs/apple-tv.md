# Apple TV / tvOS (experimental)

Manager 0.7.16 adds tvOS virtual-file support while retaining Android/Shield behavior and all
existing layout source/version gates. The same ZIP runs inside Kodi; the dashboard needs a browser
and direct LAN access. It does not install or sign Kodi itself. Use a working Kodi installation on
Apple TV HD/4K; see [Kodi's tvOS page](https://kodi.wiki/view/TvOS). Physical Apple TV validation is
pending; synthetic tests establish the storage/refusal contracts, not firmware compatibility.

## Installation

1. Open Kodi and follow [the repository installation steps](setup.md#1-add-the-download-source--inside-kodi).
   You enter the source address with the remote; no computer file transfer is needed.
2. Follow [dashboard setup](setup.md#3-enable-dashboard-access) to turn on **Allow LAN access**.
3. Open **Home → Add-ons → Video add-ons → Kodi Manager → Open the dashboard on another device**.
4. On your phone/computer, open the displayed address and enter the token privately. Keep Kodi active.

If only Configure is available, use the [Auth token fallback](setup.md#only-configure-is-available).
Keep write mode off initially. Tokens belong to the active Kodi profile.
For offline/pinned installation, use [a ZIP on a private network share](setup-agent.md#manual-zip-installation).

There is no ADB push, Android storage root or loopback forwarding on Apple TV. Initial installation
and Kodi security settings use Kodi's own UI. For optional assistant controls, use
[nvidia-MCP's Apple TV guide](https://github.com/glasgowm148/nvidia-MCP/blob/main/docs/apple-tv.md):
the computer agent installs the optional pyatv dependency, pairs privately and preserves an
existing Shield configuration in a separate server entry.

## Skin, settings and widgets

Inspect installed versions and the active skin/profile first. Supported layout editing still uses
inspect -> preview -> apply, source hashes, expected revision, backup and rollback. Reviewed Bingie
2.0.2 / Skin Shortcuts 2.0.3 are writable; unknown forks or modified source stay view-only. Cached
rows, sources, provider previews, non-credential settings and backup/restore use the existing APIs.
Kodi/add-on dependencies must themselves support tvOS. This release does not install a skin or
claim universal add-on compatibility.

Keep Kodi active on the TV. Manager reads native `UIApplication.applicationState`; inactive,
background or unreadable state blocks POST/PATCH action requests, including read-only previews
and forced restores. A checkpoint copy stops if focus is lost. This adds no UI actions or
background-execution entitlement. The dashboard may stop answering when tvOS suspends Kodi;
open Kodi again, inspect what completed and avoid automatically retrying writes. The optional
MCP backend also checks paired system media and Kodi players before changes.

## Storage and recovery

Kodi's tvOS userdata XML lives in VFS/NSUserDefaults, as shown in
[Kodi's TVOSFile implementation](https://github.com/xbmc/xbmc/blob/master/xbmc/platform/darwin/tvos/filesystem/TVOSFile.cpp).
Kodi excludes `customcontroller.SiriRemote*.xml` from virtual storage. From Manager 0.7.20,
these controller files retain normal physical reads, atomic replacement and backup.
Manager explicitly reads other userdata XML from its virtual value, writes XML in one call, checks readback and restores
the previous value on failure. Backups, undo, pipeline snapshots and pruning use virtual XML;
stale physical shadows cannot replace it after a failed VFS read. Android retains its normal
POSIX atomic writes. Virtual XML readback/backups are limited to 2 MB per file. From 0.7.17, incomplete/changed VFS reads and empty/oversized virtual writes are refused before accepting a snapshot or changing a preference. Version 0.7.18 also verifies existence/stat against the handle, since Kodi's Python constructor can silently ignore a failed native open.

From 0.7.22, backup paths retain Kodi's translated directory spelling for virtual XML keys,
including aliases such as `/var` -> `/private/var`. Canonical paths are used only for confinement.
Take a fresh validated snapshot after updating: older alias-affected physical XML snapshots may
be refused as incomplete. Missing virtual keys never fall back to physical shadows; retained
files are left intact. Keep independent private recovery copies.

Non-XML files, directories, cache databases and backup manifests remain disposable tvOS storage.
A missing source directory cannot enumerate retained XML keys; Manager refuses that snapshot instead of treating it as empty. Reopen the affected add-on on the TV to recreate its directories, then inspect before backing up. Purged subdirectories/manifests cannot establish a complete recoverable snapshot.

On-device configuration snapshots provide useful undo while intact, not durable disaster
recovery. A raw filesystem/SMB copy may omit real preference values. Keep important configuration
in separate private computer copies using VFS-aware reads; the MCP file reader can snapshot
selected text files, but cannot restore those snapshots offline on tvOS. APK/IPA installation,
app-container backup, signing renewal, shell access and hung-process force-stop are outside
Manager. Do not uninstall Kodi to fix a settings problem without independent recovery data.

From 0.7.23, canonical userdata paths used by layout inspection also map back to Kodi's
translated VFS keys. Aliases share write locks and cannot read stale physical XML shadows.
Failed per-file readback preserves a distinct native editor value/deletion rather than
blindly rolling it back; unknown ownership retains the backup for inspection. Finish native
editing before a full configuration restore, which replaces the requested folder.

From 0.7.23, request handlers stay bound to their service profile. A stopped generation or
changed profile returns a conflict; delayed action bodies recheck the current token and write
switch. Backup, undo, rollback and retention keep the root captured for that operation, even
if a profile switch happens. Reconnect and inspect before retrying: work already dispatched
to Kodi may have completed. These checks do not lock Kodi's native profile UI.

## Portable read API

Authenticated `/api/portable/state` reports platform, native active state, active profile/path and
a persistent Manager-instance ID. `/api/portable/file?path=…` reads active-profile or installed
add-on text, bounded to 600 KB, with byte count/base64/SHA-256. Version 0.7.17 adds device/profile ownership to the response and optional expected ownership query fields. From 0.7.20, this also excludes configured profiles nested beneath the active profile.
Version 0.7.21 preserves translated VFS key paths when master userdata uses a directory alias. It rejects other profiles, traversal,
symlinks and non-text extensions. The bearer token can read private configuration through this
API; never expose it or attach snapshots to bug reports. There is no arbitrary file-write API.
The ID identifies this Manager installation, not the Apple TV hardware; deletion/cloning of
userdata can change/copy it. Self-restore preserves the live identity and access settings, including failed restore rollback
from 0.7.22.

Before promoting tvOS support, verify on a spare/backed-up device: installation/auth, both profiles,
active/background detection, one reversible setting/layout edit and undo, cache refresh,
configuration restore and actual app relaunch. Record model/tvOS/Kodi/skin/helper versions. Unknown
native active state keeps writes blocked; the existing household Shield was not changed.
