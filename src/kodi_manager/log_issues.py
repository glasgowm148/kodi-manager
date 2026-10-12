"""Conservative issue identities and advice from masked log evidence, without Kodi calls."""
import hashlib
import re
from urllib.parse import urlsplit

try:
    from .log_scan import LOG_LEVEL
    from .validation import redact
except ImportError:
    from log_scan import LOG_LEVEL
    from validation import redact

ADDON = re.compile(r"(?:[/\\]addons[/\\]|plugin://|\[|Unknown addon id ['\"])([a-z]+\.[\w.-]+)", re.I)
URL = re.compile(r"https?://[^\s<>\"']+", re.I)


def url_host(url):
    try:
        return urlsplit(url).hostname or 'URL'
    except ValueError:
        return 'URL'


def describe_issue(line):
    line = redact(line)
    parsed = LOG_LEVEL.match(line)
    message = parsed.group(2) if parsed else line.strip()
    match = ADDON.search(message)
    addon = match.group(1).rstrip('.') if match else None
    owner = {"addon_id": addon, "label": addon or "Source unconfirmed", "confidence": "explicit" if addon else "unknown"}
    family = "message"
    title = "Recorded problem"
    explanation = "This message needs its surrounding log context to establish the cause."
    action = "Open its entries and check what happened immediately before the message."
    signature = message

    if 'timed out waiting for renderer to flush' in message:
        family, title = 'renderer-flush', 'Display renderer flush timed out'
        owner = {"addon_id": None, "label": "Kodi video renderer", "confidence": "native"}
        explanation = "Kodi did not finish a renderer flush within its deadline. A display-rate change can trigger this."
        action = "Check for a visible freeze or failed playback, and note the display rate when reporting it to Kodi."
    elif 'timeout waiting for buffer' in message:
        family, title = 'video-buffer', 'Video output waited for a buffer'
        owner = {"addon_id": None, "label": "Kodi video renderer", "confidence": "native"}
        explanation = "The video output did not receive a usable buffer in time, including during playback shutdown."
        action = "Check whether this occurs during normal playback or only when stopping a video."
    elif 'Passing None where a string is expected' in message:
        family, title = 'missing-string', 'An add-on supplied a missing string'
        explanation = "An add-on passed an absent value to a Kodi API that expects text. Newer Kodi versions may reject it."
        action = "Update the responsible add-on. If its source is unconfirmed, reproduce once with debug logging to identify the caller."
    elif 'left several classes in memory' in message:
        family, title = 'native-handles', 'An add-on retained Kodi objects'
        explanation = "The Python script ended while references to native Kodi objects remained."
        action = "Update this add-on and check whether the same warning returns after running or closing it."
    elif 'Kodi is not playing any media file' in message:
        family, title = 'stopped-player', 'A script queried an inactive player'
        explanation = "A script requested playback information after Kodi's player was no longer active."
        action = "Check for recurrence when stopping or switching a video and update the responsible add-on."
    elif 'Unknown addon id' in message:
        family, title = 'missing-addon', 'A script referenced an unavailable add-on'
        explanation = "Another script tried to access an add-on that Kodi could not open, including an installed but disabled add-on."
        action = "Check the named add-on's installed/enabled state and the integration that references it."
        owner['label'] = ('Referenced add-on: ' + addon) if addon else 'Referenced add-on unconfirmed'
        owner['confidence'] = 'referenced' if addon else 'unknown'
    elif 'GetDirectory - Error getting plugin://' in message:
        family, title = 'addon-directory', 'An add-on directory request failed'
        explanation = "Kodi could not load a requested add-on route. That route may need details the current item does not provide."
        action = "Check whether opening the add-on directly also fails, and inspect this entry's route before changing its settings."
    elif 'CCurlFile::Stat' in message:
        family, title = 'http-stat', 'A network file check failed'
        owner['label'] = addon or 'Kodi networking'
        explanation = "Kodi's network metadata check failed. This alone does not establish that the video failed to play."
        action = "Try the same item through Kodi's normal interface and check for a playback failure before changing the provider."
        hosts = [url_host(url) for url in URL.findall(message)]
        signature = ' '.join(hosts) + re.sub(r'<.*?>', '<URL>', message)
    elif 'no such table:' in message:
        family, title = 'cache-table', 'An add-on cache table was unavailable'
        explanation = "A database query referenced a table that was absent. Some add-ons create cache tables on their first use."
        action = "Check whether it returns during ordinary use. Identify the add-on before repairing its cache."
        table = re.search(r'no such table:\s*([\w.]+)', message)
        signature = table.group(1) if table else message
    elif re.fullmatch(r'Skipped \d+ duplicate messages\.\.', message):
        family, title = 'duplicates', 'Kodi suppressed repeated messages'
        explanation = "This saved line reports suppressed duplicates; its original cause cannot be identified from this line alone."
        action = "Check nearby original messages. Counts here describe recorded entries, not the hidden duplicate total."
    elif 'Trying to add unsupported control type' in message:
        family, title = 'skin-control', 'A skin requested an unsupported control'
        explanation = "Kodi logged a skin control it does not support. Reviewed compatibility notices retain their original classification."
        action = "Check the active skin and whether its controls work normally."

    if family not in ('message', 'http-stat', 'cache-table'):
        signature = family
    signature = URL.sub(lambda m: url_host(m.group()), signature)
    signature = re.sub(r'CPythonInvoker\(\d+', 'CPythonInvoker(<id>', signature)
    signature = re.sub(r'0x[0-9a-f]+|\bline \d+\b', '<position>', signature, flags=re.I)
    key = hashlib.sha256((family + '\0' + (addon or '') + '\0' + signature).encode()).hexdigest()[:32]
    return key, dict(family=family, title=title, owner=owner, explanation=explanation, next_step=action)
