"""tvOS userdata XML lives in Kodi's VFS/NSUserDefaults, not POSIX files.

Other platforms retain their existing filesystem operations. Never fall back to a
stale physical XML shadow after a tvOS VFS failure. Non-XML caches remain disposable.
"""
import os
import shutil

try:
    import xbmc
    import xbmcvfs
except ImportError:
    xbmc = xbmcvfs = None


def is_tvos():
    return bool(xbmc and xbmc.getCondVisibility("System.Platform.TVOS"))


def userdata(path):
    if not is_tvos() or not xbmcvfs:
        return False
    root = os.path.abspath(xbmcvfs.translatePath("special://masterprofile/"))
    target = os.path.abspath(os.fspath(path))
    return os.path.commonpath([root, target]) == root


def virtual_xml(path):
    return str(path).lower().endswith(".xml") and userdata(path)


def exists(path):
    return bool(xbmcvfs.exists(str(path))) if virtual_xml(path) and xbmcvfs else os.path.exists(path)


def is_file(path):
    return exists(path) if virtual_xml(path) else os.path.isfile(path)


def size(path):
    return len(read_bytes(path)) if virtual_xml(path) else os.path.getsize(path)


def read_bytes(path, limit=2_000_000):
    if virtual_xml(path) and xbmcvfs:
        handle = xbmcvfs.File(str(path))
        try:
            expected = handle.size()
            if type(expected) is not int or expected < 0:
                raise OSError("Kodi virtual file length is unreadable")
            if expected > limit:
                raise ValueError("File exceeds the size limit")
            data = bytes(handle.readBytes(limit + 1))
            if len(data) != expected or handle.size() != expected:
                raise OSError("Kodi virtual file read was incomplete or changed")
        finally:
            handle.close()
    else:
        with open(path, "rb") as handle:
            data = handle.read(limit + 1)
    if len(data) > limit:
        raise ValueError("File exceeds the size limit")
    return data


def remove(path):
    if virtual_xml(path) and xbmcvfs:
        if exists(path) and not xbmcvfs.delete(str(path)):
            raise OSError("Kodi virtual file could not be removed")
        if os.path.lexists(path):
            os.remove(path)  # Remove a legacy POSIX shadow too; it must not reappear.
    else:
        os.remove(path)


def listdir(path):
    if userdata(path) and xbmcvfs:
        dirs, files = xbmcvfs.listdir(str(path).rstrip("/\\") + "/")
        return sorted(set(dirs + files))
    return os.listdir(path)


def walk(path, topdown=True):
    if not userdata(path) or not xbmcvfs:
        yield from os.walk(path, topdown=topdown)
        return
    dirs, files = xbmcvfs.listdir(str(path).rstrip("/\\") + "/")
    dirs, files = sorted(set(dirs)), sorted(set(files))
    if topdown:
        yield str(path), dirs, files
    for name in dirs:  # The caller may prune dirs, just as with os.walk.
        if not os.path.islink(os.path.join(path, name)):
            yield from walk(os.path.join(path, name), topdown=topdown)
    if not topdown:
        yield str(path), dirs, files


def rmtree(path, ignore_errors=False):
    if userdata(path) and xbmcvfs:
        for root, _dirs, files in walk(path):
            for name in files:
                target = os.path.join(root, name)
                if virtual_xml(target):
                    try:
                        remove(target)
                    except OSError:
                        if not ignore_errors:
                            raise
    shutil.rmtree(path, ignore_errors=ignore_errors)


def write_xml(path, data):
    """One preference-key write plus readback; restore the old key on failure.

    tvOS's CTVOSFile::Write replaces the whole value on every call, so never stream
    chunks or use POSIX rename to replace a virtual XML key.
    """
    assert xbmcvfs is not None
    vfs = xbmcvfs
    old = read_bytes(path) if exists(path) else None
    if not data or len(data) > 2_000_000 or old == b"":
        # Kodi's Python write wrapper never calls Write for an empty buffer, so
        # an empty preference cannot be created/restored reliably through it.
        raise ValueError("Virtual XML must be nonempty and within the size limit")

    def save(value):
        handle = vfs.File(str(path), "w")
        try:
            if not handle.write(bytearray(value)):
                raise OSError("Kodi virtual file write failed")
        finally:
            handle.close()

    try:
        save(data)
        if read_bytes(path) != data:
            raise OSError("Kodi virtual file readback differs")
    except BaseException:
        try:
            remove(path) if old is None else save(old)
            if (old is None and exists(path)) or (old is not None and read_bytes(path) != old):
                raise OSError("Virtual file rollback readback differs")
        except Exception:
            raise OSError("Virtual file write and rollback failed; inspect the retained backup") from None
        raise


def application_active():
    """Read UIApplicationState; unknown/inactive/background never means idle.

    The same read-only getter is used by Kodi's tvOS controller. No UIKit actions,
    dispatch callbacks, native plug-ins or background execution requests are added.
    """
    if not is_tvos():
        return None
    try:
        import ctypes
        objc = ctypes.CDLL("/usr/lib/libobjc.A.dylib")
        objc.objc_getClass.restype = ctypes.c_void_p
        objc.objc_getClass.argtypes = [ctypes.c_char_p]
        objc.sel_registerName.restype = ctypes.c_void_p
        objc.sel_registerName.argtypes = [ctypes.c_char_p]
        send_pointer = ctypes.CFUNCTYPE(ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p)(("objc_msgSend", objc))
        send_integer = ctypes.CFUNCTYPE(ctypes.c_long, ctypes.c_void_p, ctypes.c_void_p)(("objc_msgSend", objc))
        cls = objc.objc_getClass(b"UIApplication")
        if not cls:
            return None
        app = send_pointer(cls, objc.sel_registerName(b"sharedApplication"))
        if not app:
            return None
        state = send_integer(app, objc.sel_registerName(b"applicationState"))
        return state == 0 if state in (0, 1, 2) else None
    except Exception:
        return None


def require_active():
    if is_tvos() and application_active() is not True:
        raise ValueError("Kodi is not confirmed active on Apple TV; no change performed")
