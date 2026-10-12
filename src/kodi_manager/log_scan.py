"""Log-level parsing and narrowly evidenced compatibility notices."""
import re

LOG_LEVEL = re.compile(r"^(?:\d{4}-\d{2}-\d{2}\s+\S+\s+T:\d+\s+)?"
                       r"(debug|info|notice|warning|warn|error|fatal)\b(?:\s*<[^>]*>)?\s*:?\s*(.*)$", re.I)


def classify_line(line, following=(), skin=None, prior_notice=False):
    parsed = LOG_LEVEL.match(line)
    if not parsed:
        return ("error" if re.search(r"\b(error|exception|traceback)\b", line, re.I) else None), prior_notice
    level, message = parsed.group(1).lower(), parsed.group(2)
    if level in ("error", "fatal"):
        return "error", False
    if level not in ("warning", "warn"):
        return None, False
    if re.fullmatch(r"Skipped \d+ duplicate messages\.\.", message):
        return ("notice" if prior_notice else "warning"), prior_notice
    skin = skin or {}
    focus_buttons = (skin.get("active") and skin.get("addon_id") == "skin.bingie"
                     and skin.get("version") in ("2.0.2.3", "2.0.2.5"))
    resolved_type = (message == 'JSONRPC: Could not parse type "Setting.Details.SettingList"'
                     and any("JSONRPC: Resolving incomplete types/methods referencing Setting.Details.Setting"
                             in other for other in following))
    notice = bool(resolved_type or (focus_buttons and message == "Trying to add unsupported control type 7"))
    return ("notice" if notice else "warning"), notice


def scan_log_lines(lines, skin=None):
    """Keep every raw warning; only reviewed notices bypass the Health alert."""
    errors, warnings, notices, raw_warnings = [], [], [], []
    prior_notice = False
    for i, line in enumerate(lines):
        kind, prior_notice = classify_line(line, lines[i + 1:i + 6], skin, prior_notice)
        if kind == "error":
            errors.append(line)
        elif kind:
            (notices if kind == "notice" else warnings).append(line)
            raw_warnings.append(line)
    return errors, warnings, notices, raw_warnings
