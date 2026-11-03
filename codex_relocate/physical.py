"""Read-only physical-path and security metadata. Never takes ownership or changes ACLs."""
import ctypes as c
from ctypes import wintypes as w
import os
import re

from . import windows as win


def directory(path):
    win.require_local(path)
    k = win.kernel()
    k.CreateFileW.argtypes = [w.LPCWSTR, w.DWORD, w.DWORD, c.c_void_p,
                             w.DWORD, w.DWORD, w.HANDLE]
    k.CreateFileW.restype = w.HANDLE
    k.GetFinalPathNameByHandleW.argtypes = [w.HANDLE, w.LPWSTR, w.DWORD, w.DWORD]
    k.CloseHandle.argtypes = [w.HANDLE]
    handle = k.CreateFileW(win.extended(path), 0, 7, None, 3, 0x02000000, None)
    if handle == c.c_void_p(-1).value:
        raise c.WinError(c.get_last_error())
    try:
        buf = c.create_unicode_buffer(32768)
        count = k.GetFinalPathNameByHandleW(handle, buf, len(buf), 0)
        if not count or count >= len(buf):
            raise c.WinError(c.get_last_error())
        value = buf.value
        if value.startswith('\\\\?\\UNC\\'):
            return '\\\\' + value[8:]
        return value[4:] if value.startswith('\\\\?\\') else value
    finally:
        k.CloseHandle(handle)


def security(path):
    a = c.WinDLL('advapi32', use_last_error=True)
    a.GetFileSecurityW.argtypes = [w.LPCWSTR, w.DWORD, c.c_void_p,
                                  w.DWORD, c.POINTER(w.DWORD)]
    needed = w.DWORD()
    a.GetFileSecurityW(win.extended(path), 7, None, 0, c.byref(needed))
    if not needed.value:
        raise c.WinError(c.get_last_error())
    data = c.create_string_buffer(needed.value)
    if not a.GetFileSecurityW(win.extended(path), 7, data, len(data), c.byref(needed)):
        raise c.WinError(c.get_last_error())
    a.ConvertSecurityDescriptorToStringSecurityDescriptorW.argtypes = [
        c.c_void_p, w.DWORD, w.DWORD, c.POINTER(w.LPWSTR), c.POINTER(w.DWORD)]
    text = w.LPWSTR()
    if not a.ConvertSecurityDescriptorToStringSecurityDescriptorW(
            data, 1, 7, c.byref(text), None):
        raise c.WinError(c.get_last_error())
    try:
        sddl = text.value
    finally:
        k = win.kernel()
        k.LocalFree.argtypes = [c.c_void_p]
        k.LocalFree(c.cast(text, c.c_void_p))
    owner = re.search(r'O:(.*?)(?=[GDS]:|$)', sddl)
    dacl = re.search(r'D:([^()]*)', sddl)
    return {'owner': owner.group(1) if owner else None,
            'dacl_protected': bool(dacl and 'P' in dacl.group(1)),
            'read_control': True}


def key(path):
    return os.path.normcase(os.path.normpath(str(path)))
