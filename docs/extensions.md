# Private extensions

Kodi Manager releases contain only Kodi Manager's own code. A private build (for example one
person's own TV) can add behaviour without patching the core files by placing one optional module,
`household.py`, next to the add-on's other Python files (`resources/lib/` in the add-on,
`src/kodi_manager/` before building). Public builds ship no such module and behave exactly as if
the hook did not exist; `scripts/check_release.py` rejects a release archive that contains one.

The module is loaded once per Python interpreter by `extension.py`. It must import nothing heavy at
module level, because the plugin entry point loads it on every directory request. If it fails to
import, Kodi Manager carries on without it and the service logs `Private extension unavailable:
<error type>`.

Everything the module defines is optional:

| Name | Used by | Meaning |
|---|---|---|
| `start(monitor, log)` | service | Called once after the dashboard and the exit workaround are set up. `monitor` is the service's startup monitor (its `abortRequested()` also turns true when a coordinated profile switch cancels this service); `log` writes a Kodi Manager log line. Failures are logged by type and ignored. |
| `stop()` | service | Called first when the service stops. |
| `widget_mode(mode, argv)` | plugin | Offered every plugin `mode` the public code does not handle (not `family`). Return `True` after answering the directory request; `False` keeps the public behaviour (the request fails as unsupported). |
| `WIDGET_PROGRESS_MODES` | widget cache | Extra `mode` values whose cached rows are progress rows: 15-minute lifetime, refreshed first after playback. |
| `WIDGET_PLAYABLE_MODES` | widget cache | `{add-on ID: modes}`. Cached leaves of that add-on whose `mode` is listed resolve with `setResolvedUrl`, so they are marked playable; other leaves of that add-on are not. |
| `TRANSITION_COORDINATOR` | `profile_transition.py` | Add-on ID of a profile-switch coordinator (below). |

## Coordinated profile switches

Some setups switch profiles through their own add-on, which announces the switch before Kodi takes
its GUI and profile locks. With `TRANSITION_COORDINATOR` set, Kodi Manager follows that protocol
through files in the coordinator's master-profile `addon_data` folder:

- `transition.json` (`pid`, `generation`, `switching`, `outgoing`) is read, never written. When the
  generation changes, or a switch away from the current profile starts, the service's monitor
  reports abort and plugin calls stop rendering.
- Each plugin call registers `jobs/<pid>/<id>.json` (`profile`, `addon`) while it runs, and waits for
  the threads it started before removing it.
- On exit the service waits up to 10 seconds for its own threads, then writes
  `drained/<generation>/service.kodi.addonadmin.json` (or `drain-diagnostic.json` with thread names).

Only generation, process ID, profile paths and add-on IDs are stored. Without a coordinator none of
these files are read or written, threads are not tagged and the monitor is a plain `xbmc.Monitor`.
