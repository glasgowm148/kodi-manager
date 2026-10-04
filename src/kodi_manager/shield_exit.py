"""Opt-in workaround for the Shield's native crash after Kodi's Stop phase."""
import os
import re
import subprocess
import time


def process_start(pid):
    with open('/proc/%d/stat' % pid, encoding='utf-8') as handle:
        # comm may contain spaces or parentheses; field 22 follows its closing ).
        return handle.read().rsplit(') ', 1)[1].split()[19]


def shutdown_started(text):
    return bool(re.search(r'^.*\binfo <general>: (?:XBMCApp: )?Stopping the application\.\.\.$', text, re.M))


class ShieldExitGuard:
    def __init__(self, enabled, log_path, script_path, result_path):
        self.enabled = enabled
        self.log_path = log_path
        self.script_path = script_path
        self.result_path = result_path
        self.child = None
        self.offset = os.path.getsize(log_path) if enabled and os.path.isfile(log_path) else 0

    def arm(self):
        if not self.enabled or self.child is not None:
            return
        pid = os.getpid()
        start = process_start(pid)
        # A long session can produce megabytes of log history. The shell
        # watcher needs recent shutdown markers, not the whole session.
        offset = max(self.offset, os.path.getsize(self.log_path) - 65536)
        try:
            stderr = open(self.result_path + '.stderr', 'wb')
        except OSError:
            stderr = subprocess.DEVNULL
        try:
            self.child = subprocess.Popen(
                ['/system/bin/sh', self.script_path, str(pid), start,
                 self.log_path, str(offset), self.result_path],
                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                stderr=stderr, start_new_session=True, close_fds=True)
        finally:
            if hasattr(stderr, 'close'):
                stderr.close()

    def on_abort(self):
        # Profile changes also abort services. Launch only for a real Kodi Stop.
        if not self.enabled or self.child is not None:
            return
        # Abort callbacks and the native shutdown log arrive on different
        # threads. Allow the marker to catch up before treating this as a
        # profile change. Never arm from records preceding this service.
        for attempt in range(11):
            with open(self.log_path, 'rb') as handle:
                handle.seek(max(self.offset, os.path.getsize(self.log_path) - 65536))
                text = handle.read().decode('utf-8', errors='replace')
            if shutdown_started(text):
                self.arm()
                return
            if attempt < 10:
                time.sleep(.05)
