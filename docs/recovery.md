# Configuration recovery

Backups belong to the active Kodi profile and can contain passwords/tokens. Keep a separate private
copy before replacing a customized service. They are stored under
`special://profile/addon_data/service.kodi.addonadmin/backups`.

1. Confirm viewing is finished, the intended profile is active and the service's write mode is enabled
   for this change. Keep account credentials out of logs/issues.
2. Create an add-on or stack checkpoint. Verify its manifest and copied files privately before edits.
   Version 0.4.1 appends a unique suffix to the timestamp, so rapid checkpoints stay distinct.
3. Restore the selected checkpoint. The service first saves current configuration separately.
   Add-on responses return `undo_backup_id`; stack responses return an `undo_backups` map by add-on.
   Older timestamp-only backup IDs remain accepted.
4. Restart Kodi when viewing is finished if the response requires it. Inspect settings and behavior;
   an HTTP success alone does not prove the runtime has reloaded them.
5. To undo, restore the returned safety backup for each affected add-on. Keep originals until the
   result is verified, then disable write mode.

Restore copies the recorded configuration files; it does not remove newly created files, provide a
filesystem-wide transaction, restore Android private data, downgrade Kodi or migrate cloud history.
Pipeline snapshots are currently inspected/restored manually. Retention is not automatically enforced;
inspect and remove old backups privately after keeping a verified external copy.

For APK upgrade preparation use [nvidia-MCP's APK recovery guide](https://github.com/glasgowm148/nvidia-MCP/blob/main/docs/apk-upgrades.md).
Do not uninstall Kodi merely to bypass Android's downgrade checks; this can erase app data.
