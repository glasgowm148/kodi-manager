"""The service's background work: the widget cache refresher, row health, and the watchdog that
checks the connection and memory, runs nightly maintenance and samples the 7-day history.

Everything waits for a quiet TV (``BUSY_CONDITION``) before doing anything heavy.
"""
import json
import os
import time

try:
    import xbmc
except ImportError:
    xbmc = None

try:
    from . import tvos_storage
    from .kodi_api import translate
    from .widget_cache import WidgetCache, jsonrpc_via, RELOAD_PROPERTY
    from .widget_refresher import Refresher
except ImportError:
    import tvos_storage
    from kodi_api import translate
    from widget_cache import WidgetCache, jsonrpc_via, RELOAD_PROPERTY
    from widget_refresher import Refresher


# Refresh cached rows only while the TV is quiet: no media loaded, no busy or
# progress dialog (POV searching for sources), no modal dialog and no remote
# press for a minute.
BUSY_CONDITION = ("Player.HasMedia | Window.IsActive(busydialog) | Window.IsActive(busydialognocancel)"
                  " | Window.IsActive(progressdialog) | Window.IsActive(extendedprogressdialog)"
                  " | Window.IsActive(progress_media.xml) | System.HasModalDialog | !System.IdleTime(60)")


# Window(10000) properties widget add-ons bump after a library or Trakt sync;
# a change refreshes the personal (progress) rows at the same time.
EXTERNAL_RELOAD_PROPERTIES = ("TMDbBingieHelper.Widgets.Reload", "TMDbHelper.Widgets.Reload", "POV.Widgets.Reload")
WIDGET_FAILURES_PROPERTY = "KM.WidgetFailures"


def external_reload_token(home):
    return "|".join(home.getProperty(name) for name in EXTERNAL_RELOAD_PROPERTIES)


def persistent_widget_failures(cache):
    """Count failed active rows without parsing their large artwork listings."""
    try:
        names = os.listdir(cache.health_dir)
    except OSError:
        return 0
    count = 0
    for name in names:
        if not name.endswith(".json") or not os.path.isfile(os.path.join(cache.entries, name)):
            continue
        try:
            with open(os.path.join(cache.health_dir, name), encoding="utf-8") as handle:
                record = json.load(handle)
            if isinstance(record, dict) and int(record.get("failures", 0)) >= 3:
                count += 1
        except (OSError, ValueError, TypeError):
            pass
    return count


class WidgetHealth:
    """Publish how many cached rows keep failing (KM.WidgetFailures, for skins).

    Checked at most once a minute and only while the TV is quiet. One brief
    notice per failure episode: it shows again only after the rows recovered.
    """
    INTERVAL = 60

    def __init__(self, cache, set_property, notify, clock=time.time):
        self.cache, self.set_property, self.notify, self.clock = cache, set_property, notify, clock
        self.next_check = 0
        self.warned = False

    def tick(self, is_quiet):
        if self.clock() < self.next_check or not is_quiet():
            return
        self.next_check = self.clock() + self.INTERVAL
        persistent = persistent_widget_failures(self.cache)
        self.set_property(WIDGET_FAILURES_PROPERTY, str(persistent))
        if persistent and not self.warned:
            self.notify()
        self.warned = bool(persistent)


def start_widget_refresher(kodi):
    """Refresh cached widget rows one at a time in the background."""
    if not xbmc:
        return None
    import threading
    import xbmcgui
    cache = WidgetCache(translate("special://profile/addon_data/service.kodi.addonadmin/widget_cache"))
    home = xbmcgui.Window(10000)
    player = xbmc.Player()
    refresher = Refresher(cache, jsonrpc_via(xbmc), player.isPlayingVideo,
                          lambda value: home.setProperty(RELOAD_PROPERTY, value), kodi.log,
                          external_reload=lambda: external_reload_token(home),
                          is_busy=tv_busy)
    refresher.stop = threading.Event()
    refresher.sleep = refresher.stop.wait
    health = WidgetHealth(cache, home.setProperty, lambda: xbmcgui.Dialog().notification(
        "TV rows", "Some rows are unavailable. Cached results are being kept.",
        xbmcgui.NOTIFICATION_INFO, 4000, False))

    def run():
        while not refresher.stop.is_set():
            try:
                refresher.tick(refresher.stop.is_set)
                health.tick(refresher._quiet)
            except Exception as error:
                kodi.log("Widget cache refresh error: %s" % type(error).__name__)
            refresher.stop.wait(2)

    # Daemon: profile changes stop scripts while Kodi calls may block.
    threading.Thread(target=run, name="km-widget-cache", daemon=True).start()
    return refresher


def tv_busy():
    """True while the TV is in use (see BUSY_CONDITION); False outside Kodi."""
    if tvos_storage.is_tvos() and tvos_storage.application_active() is not True:
        return True
    if not xbmc:
        return False
    try:
        return bool(xbmc.getCondVisibility(BUSY_CONDITION))
    except Exception:
        return True


def start_maintenance(kodi, is_busy=tv_busy, stopping=lambda: False):
    """Nightly checkpoint, protected-settings check and account checks (see maintenance.py).

    ``stopping`` is true once the service is exiting: a checkpoint in progress stops and is
    discarded, so Kodi does not have to wait for it or kill it part way.
    """
    try:
        try:
            from .maintenance import Maintenance, nightly_checkpoint
            from .account_health import trakt_status, torbox_status, run_checks
            from .addon_index import AddonIndex
            from .backup import create_stack_backup, list_backups, delete_stack_backup
            from .dashboard_data import stack_backup_addons, make_baseline
        except ImportError:
            from maintenance import Maintenance, nightly_checkpoint
            from account_health import trakt_status, torbox_status, run_checks
            from addon_index import AddonIndex
            from backup import create_stack_backup, list_backups, delete_stack_backup
            from dashboard_data import stack_backup_addons, make_baseline
    except Exception as error:
        kodi.log("Maintenance unavailable: %s" % type(error).__name__)
        return None
    index = AddonIndex(kodi)

    def checkpoint():
        index.refresh(force=True)
        return nightly_checkpoint(
            # Copying addon_data competes with playback for storage: stop if the TV gets busy
            # or the service is exiting.
            lambda: create_stack_backup(stack_backup_addons(kodi, index), kodi.get_kodi_version(), note="nightly",
                                        should_stop=lambda: stopping() or is_busy()),
            lambda: list_backups(stack=True), delete_stack_backup)

    def accounts():
        return run_checks([lambda: trakt_status(kodi.get_addon_setting),
                           lambda: torbox_status(kodi.get_addon_setting, translate)], kodi.log)

    try:
        nightly = [b for b in list_backups(stack=True) if b.get("note") == "nightly"]
        last = max(str(b.get("backup_id", ""))[:8] for b in nightly) if nightly else ""
        last_day = "%s-%s-%s" % (last[:4], last[4:6], last[6:8]) if len(last) == 8 else None
    except Exception:
        last_day = None
    return Maintenance(lambda title, message: kodi.notify(title, message), baseline=make_baseline(kodi),
                       accounts=accounts, checkpoint=checkpoint, log=kodi.log, last_nightly_day=last_day,
                       is_quiet=lambda: not is_busy())


def start_sampler(kodi, memory, internet):
    """The dashboard's 7-day history (metrics.py), sampled from the watchdog loop while idle."""
    try:
        try:
            from .metrics import HISTORY_FILE, MetricsHistory, Sampler, widget_row_counts
        except ImportError:
            from metrics import HISTORY_FILE, MetricsHistory, Sampler, widget_row_counts
        rows_root = translate("special://profile/addon_data/service.kodi.addonadmin/widget_cache")
        return Sampler(MetricsHistory(translate(HISTORY_FILE)), memory, internet,
                       lambda: widget_row_counts(rows_root))
    except Exception as error:
        kodi.log("Metrics history unavailable: %s" % type(error).__name__)
        return None


def start_watchdog(kodi):
    """Background connection and memory check; notifies once when something is wrong."""
    import threading
    try:
        from .netwatch import Watchdog, latest_internet
        from .memstat import memory_status
    except ImportError:
        from netwatch import Watchdog, latest_internet
        from memstat import memory_status
    watchdog = Watchdog(lambda title, message: kodi.notify(title, message),
                        is_quiet=lambda: not tv_busy(),
                        memory=memory_status, log=kodi.log)
    watchdog.stop = threading.Event()
    housekeeping = start_maintenance(kodi, stopping=watchdog.stop.is_set)
    sampler = start_sampler(kodi, memory_status, latest_internet)

    def run():
        while not watchdog.stop.is_set():
            try:
                watchdog.tick(watchdog.stop.is_set)
            except Exception as error:
                kodi.log("Connection watchdog error: %s" % type(error).__name__)
            if housekeeping is not None and not watchdog.stop.is_set():
                try:
                    housekeeping.tick(not tv_busy())
                except Exception as error:
                    kodi.log("Maintenance error: %s" % type(error).__name__)
            if sampler is not None and not watchdog.stop.is_set():
                try:
                    # Idle only: nothing extra runs while something plays.
                    sampler.tick(not tv_busy())
                except Exception as error:
                    kodi.log("Metrics history error: %s" % type(error).__name__)
            watchdog.stop.wait(15)

    threading.Thread(target=run, name="km-watchdog", daemon=True).start()
    return watchdog
