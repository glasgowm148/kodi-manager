"""Which add-ons Kodi Manager may write settings for, and why not.

One gate for the settings editor, the pipeline editor and the account editor.
"""

SELF_ID = "service.kodi.addonadmin"

WRITES_DISABLED = "Enable writes in Kodi Manager settings"
SELF_READ_ONLY = "Kodi Manager's own settings are edited in Kodi"
NOT_ALLOWED = "Add %s to 'Allowed add-ons' in Kodi Manager settings to edit it"


class WriteRefused(PermissionError):
    """A write the configuration does not allow. ``code`` is the API error code."""

    def __init__(self, message, code="write_disabled"):
        super(WriteRefused, self).__init__(message)
        self.code = code


def allowed_addons(config_or_csv):
    csv = config_or_csv.get("allowed_addons_csv") if isinstance(config_or_csv, dict) else config_or_csv
    return {part.strip() for part in str(csv or "").split(",") if part.strip()}


def read_only_reason(addon_id, addon, config):
    """None when settings of ``addon_id`` may be written, else a sentence for the user."""
    if addon_id == SELF_ID:
        return SELF_READ_ONLY
    if not config.get("write_enabled"):
        return WRITES_DISABLED
    if not (addon or {}).get("is_stack_addon") and addon_id not in allowed_addons(config):
        return NOT_ALLOWED % addon_id
    return None


def check_writable(addon_id, addon, config):
    """Raise WriteRefused unless settings of ``addon_id`` may be written."""
    reason = read_only_reason(addon_id, addon, config)
    if reason is None:
        return
    if reason == WRITES_DISABLED:
        raise WriteRefused("Writes disabled in service settings", "write_disabled")
    if reason == SELF_READ_ONLY:
        raise WriteRefused(reason, "self_read_only")
    raise WriteRefused("Add-on is outside focused stack. " + reason, "addon_not_allowed")
