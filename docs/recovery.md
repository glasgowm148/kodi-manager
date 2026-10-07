# Configuration recovery

Backups belong to the active Kodi profile and can contain passwords and tokens. They are stored under
`special://profile/addon_data/service.kodi.addonadmin/backups`, one folder per add-on plus `_stack`
for checkpoints. Keep a separate private copy before replacing a customized installation.

## From the dashboard

- **Every change is backed up first.** Saving settings, accounts or playback controls, applying a home
  layout and repairing fixes each make a backup before writing.
- **Add-on backups.** Open an add-on's settings and choose the **Backups** tab, or pick the add-on under
  **Backups → Add-on backups**. **Restore** puts that add-on's settings folder back.
- **Checkpoints.** **Backups → Create checkpoint** saves the skin, helpers and players together.
  Restoring a checkpoint restores each of them.
- **Undo.** A restore first backs up the current settings. The notice that follows lists those undo
  backups with an **Undo restore** button. Over the API, an add-on restore returns `undo_backup_id`
  and a checkpoint restore returns an `undo_backups` map by add-on; restore those to undo.
- **Kodi busy.** If something is playing, Kodi Manager asks before restoring (the API answers `409`
  and accepts `"force": true`). Restoring while an add-on runs can be overwritten when it next saves.

Restores need **Enable writes**. If an add-on does not pick up restored settings, restart Kodi when
viewing has finished, then check the settings and behaviour: an HTTP success alone does not prove the
add-on has reloaded them.

## Retention

Kodi Manager keeps the newest **Backups to keep per add-on** (default 20) in each folder: each add-on
and the checkpoint folder separately. Older ones are deleted when a new backup is made. Copy a backup
somewhere private first if you need to keep it longer.

## Limits

Restore copies the recorded configuration files. It does not remove files created since, provide a
filesystem-wide transaction, restore Android private data, downgrade Kodi or migrate cloud history.
Playback-setting backups (`kind: pipeline`) are restored by hand: copy the files from the backup
folder back into each add-on's `addon_data` folder while Kodi is idle.

For APK upgrades, see [nvidia-MCP's APK recovery guide](https://github.com/glasgowm148/nvidia-MCP/blob/main/docs/apk-upgrades.md).
Do not uninstall Kodi to get round Android's downgrade checks: that can erase app data.
