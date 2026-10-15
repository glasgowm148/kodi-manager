"""Back up and restore tested custom files without crossing add-on versions."""
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import threading
import time
import uuid
import xml.etree.ElementTree as ET

try:
    from .write_policy import RequestRefused
except ImportError:
    from write_policy import RequestRefused

_LOCK = threading.Lock()


def digest(path):
    if not path.is_file():
        return None
    return hashlib.sha256(path.read_bytes()).hexdigest()


def safe_path(root, relative):
    part = PurePosixPath(relative)
    if part.is_absolute() or '..' in part.parts or not part.parts:
        raise ValueError('Invalid protected path')
    root = root.resolve()
    target = root.joinpath(*part.parts)
    if root not in target.resolve().parents:
        raise ValueError('Protected path leaves its directory')
    return target


class FixProtection:
    def __init__(self, addons_root, backup_root, bundle=None):
        self.root = Path(addons_root)
        self.backups = Path(backup_root)
        self.bundle = Path(bundle) if bundle else Path(__file__).resolve().parents[1] / 'device_fixes'
        manifest = self.bundle / 'manifest.json'
        self.manifest = json.loads(manifest.read_text(encoding='utf-8')) if manifest.is_file() else {'groups': []}

    def status(self):
        if not self.manifest['groups']:
            return {'healthy': None, 'groups': [], 'repairable': False, 'bundled': False,
                    'detail': 'No custom third-party fixes are bundled with the portable companion.'}
        groups = []
        for group in self.manifest['groups']:
            addon = safe_path(self.root, group['addon_id'])
            try:
                version = ET.parse(addon / 'addon.xml').getroot().get('version')
            except (OSError, ET.ParseError):
                version = None
            changed = []
            compatible = version == group['version']
            repairable = compatible
            for file in group['files']:
                target = safe_path(self.root, file['path'])
                payload = safe_path(self.bundle / 'files', file['path'])
                if digest(payload) != file['sha256']:
                    raise ValueError('Protected copy failed verification')
                actual = digest(target)
                if actual != file['sha256']:
                    known = actual in file.get('restore_from', [])
                    repairable = repairable and known
                    changed.append({'path': file['path'], 'known_previous_copy': known})
            status = 'ok' if compatible and not changed else 'changed' if compatible else 'version_changed'
            groups.append({'id': group['id'], 'label': group['label'], 'addon_id': group['addon_id'],
                           'tested_version': group['version'], 'installed_version': version,
                           'status': status, 'changed': changed, 'repairable': bool(changed and repairable)})
        return {'healthy': all(g['status'] == 'ok' for g in groups), 'groups': groups,
                'repairable': any(g['repairable'] for g in groups),
                'detail': 'Changes are checked against a verified copy. New add-on versions require review before restoring fixes.'}

    def repair(self):
        with _LOCK:
            status = self.status()
            available = {g['id'] for g in status['groups'] if g['repairable']}
            if not available:
                raise RequestRefused('No changed files can be restored safely')
            plan = []
            seen = {}
            for group in self.manifest['groups']:
                if group['id'] not in available:
                    continue
                for file in group['files']:
                    target = safe_path(self.root, file['path'])
                    if target in seen:
                        if seen[target] != file['sha256']:
                            raise ValueError('Conflicting protected copies for the same file')
                        continue
                    seen[target] = file['sha256']
                    current = digest(target)
                    if current != file['sha256']:
                        plan.append((file, target, current))
            # Unique per repair: two repairs in the same second must not collide.
            backup = self.backups / (time.strftime('%Y%m%d-%H%M%S') + '-' + uuid.uuid4().hex)
            backup.mkdir(parents=True, exist_ok=False)
            originals = []
            applied = []
            temporary = None
            try:
                # Prepare the complete backup before changing any live file.
                for file, target, current in plan:
                    if digest(target) != current:
                        raise ValueError('An add-on changed during restoration; retry when idle')
                    old = safe_path(backup, file['path'])
                    old.parent.mkdir(parents=True, exist_ok=True)
                    if current is not None:
                        shutil.copyfile(target, old)
                        if digest(old) != current:
                            raise ValueError('Backup failed verification')
                    originals.append({'path': file['path'], 'sha256': current})
                (backup / 'manifest.json').write_text(json.dumps(originals, indent=2), encoding='utf-8')
                for file, target, current in plan:
                    if digest(target) != current:
                        raise ValueError('An add-on changed during restoration')
                    payload = safe_path(self.bundle / 'files', file['path'])
                    if digest(payload) != file['sha256']:
                        raise ValueError('Protected copy changed during restoration')
                    target.parent.mkdir(parents=True, exist_ok=True)
                    temporary = target.with_name(target.name + '.km-restore')
                    shutil.copyfile(payload, temporary)
                    os.replace(temporary, target)
                    temporary = None
                    applied.append((file, target, current))
                if not all(digest(target) == file['sha256'] for file, target, _ in plan):
                    raise ValueError('Restoration failed verification')
            except Exception as error:
                if temporary is not None:
                    _unlink(temporary)
                failed = _roll_back(backup, applied)
                if failed:
                    raise RuntimeError('Restoring fixes failed (%s) and %s could not be rolled back; restore '
                                       'from %s' % (error, ', '.join(failed), backup)) from error
                # Nothing was changed: the undo copies are not needed.
                shutil.rmtree(str(backup), ignore_errors=True)
                raise
            return {'restored_files': len(plan), 'backup': str(backup), 'restart_required': True,
                    'detail': 'Tested fixes restored. Restart Kodi to load them.'}


def _unlink(path):
    try:
        path.unlink()
    except OSError:
        pass


def _roll_back(backup, applied):
    """Put back the live files a failed repair replaced, newest first, each through a
    temporary sibling so a failure cannot leave it half-written. Every file is tried;
    returns the paths that could not be put back."""
    failed = []
    for file, target, current in reversed(applied):
        temporary = target.with_name(target.name + '.km-restore')
        try:
            if current is None:
                if target.exists():
                    target.unlink()
            else:
                shutil.copyfile(safe_path(backup, file['path']), temporary)
                os.replace(temporary, target)
                if digest(target) != current:
                    raise ValueError('Rolled-back file failed verification')
        except Exception:
            failed.append(file['path'])
        finally:
            _unlink(temporary)
    return failed


def protection_for_kodi():
    try:
        from .kodi_api import translate
    except ImportError:
        from kodi_api import translate
    return FixProtection(translate('special://home/addons/'),
                         translate('special://masterprofile/addon_data/service.kodi.addonadmin/fix_backups'))
