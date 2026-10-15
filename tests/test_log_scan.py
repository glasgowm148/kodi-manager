from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src" / "kodi_manager"))
from dashboard_data import scan_log_lines  # noqa: E402


SKIN = {"active": True, "addon_id": "skin.bingie", "version": "2.0.2.3"}


def log(level, message):
    return "2026-01-01 12:00:00.000 T:123 %s <general>: %s" % (level, message)


def test_resolved_startup_type_and_reviewed_focus_buttons_keep_raw_warnings():
    lines = [log("warning", 'JSONRPC: Could not parse type "Setting.Details.SettingList"'),
             log("info", "JSONRPC: Resolving incomplete types/methods referencing Setting.Details.Setting"),
             log("warning", "Trying to add unsupported control type 7"),
             log("warning", "Skipped 30 duplicate messages..")]
    errors, warnings, notices, raw = scan_log_lines(lines, SKIN)
    assert errors == warnings == []
    assert notices == raw == [lines[0], lines[2], lines[3]]


def test_unresolved_schema_and_unknown_controls_still_warn():
    lines = [log("warning", 'JSONRPC: Could not parse type "Setting.Details.SettingList"'),
             log("warning", "Trying to add unsupported control type 17")]
    assert scan_log_lines(lines, SKIN)[1] == lines


def test_focus_notice_is_limited_to_reviewed_active_skin_version():
    lines = [log("warning", "Trying to add unsupported control type 7")]
    # The household fork's 2.0.2.N releases from 2.0.2.3 on keep the reviewed focus controls.
    for version in ("2.0.2.3", "2.0.2.4", "2.0.2.5", "2.0.2.6", "2.0.2.7", "2.0.2.8", "2.0.2.12"):
        assert scan_log_lines(lines, dict(SKIN, version=version))[2] == lines
    for skin in ({}, dict(SKIN, active=False), dict(SKIN, version="2.0.2"), dict(SKIN, version="2.0.2.2"),
                 dict(SKIN, version="2.0.3.0"), dict(SKIN, version="2.0.2.7.1"), dict(SKIN, version="12.0.2.7"),
                 dict(SKIN, version=None), dict(SKIN, version="2.0.2.x"), dict(SKIN, addon_id="skin.other")):
        assert scan_log_lines(lines, skin)[1] == lines


def test_duplicate_warning_without_known_original_remains_actionable():
    lines = [log("warning", "Skipped 30 duplicate messages..")]
    assert scan_log_lines(lines, SKIN)[1] == lines


def test_real_failures_and_deprecations_are_never_notices():
    lines = [log("error", "Playback failed"), log("fatal", "Crash"),
             log("warning", "Passing None where a string is expected is deprecated"),
             log("warning", "Skipped 30 duplicate messages..")]
    errors, warnings, notices, raw = scan_log_lines(lines, SKIN)
    assert errors == lines[:2]
    assert warnings == raw == lines[2:]
    assert notices == []


def test_info_payload_words_do_not_change_log_level():
    lines = [log("info", '"GET /api/errors HTTP/1.1" 200 -'), log("info", "No warning or exception")]
    assert scan_log_lines(lines, SKIN) == ([], [], [], [])
