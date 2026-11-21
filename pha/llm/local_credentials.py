"""Read user-scoped DPAPI credentials without logging or returning them to APIs."""
import base64
import ctypes
import json
import os
from pathlib import Path

FILE=Path(__file__).resolve().parents[2]/'.runtime/secrets/qwen.dpapi.json'


def qwen_settings():
    if not FILE.is_file():return {}
    data=json.loads(FILE.read_text(encoding='utf8'))
    return {k:data[k] for k in ('model','base_url') if isinstance(data.get(k),str)}


def qwen_key():
    return _protected_key(FILE, 'Qwen')


def deepseek_key():
    path=Path(__file__).resolve().parents[2]/'.runtime/secrets/deepseek.dpapi.json'
    return _protected_key(path, 'DeepSeek')


def _protected_key(path, label):
    if not path.is_file():return None
    if os.name!='nt':raise ValueError('Local DPAPI credentials require the same Windows account')
    from ctypes import wintypes
    class Blob(ctypes.Structure):
        _fields_=[('size',wintypes.DWORD),('data',ctypes.POINTER(ctypes.c_ubyte))]
    try:
        encrypted=base64.b64decode(json.loads(path.read_text(encoding='utf8'))['protected_key_base64'],validate=True)
        buffer=(ctypes.c_ubyte*len(encrypted)).from_buffer_copy(encrypted)
        source=Blob(len(encrypted),buffer);result=Blob()
        unprotect=ctypes.windll.crypt32.CryptUnprotectData
        unprotect.argtypes=[ctypes.POINTER(Blob),ctypes.c_void_p,ctypes.c_void_p,ctypes.c_void_p,ctypes.c_void_p,wintypes.DWORD,ctypes.POINTER(Blob)]
        unprotect.restype=wintypes.BOOL
        if not unprotect(ctypes.byref(source),None,None,None,None,1,ctypes.byref(result)):
            raise ValueError('Cannot decrypt the local '+label+' credential for this Windows account')
        try:return ctypes.string_at(result.data,result.size).decode('utf8')
        finally:
            ctypes.memset(result.data,0,result.size)
            ctypes.windll.kernel32.LocalFree.argtypes=[ctypes.c_void_p]
            ctypes.windll.kernel32.LocalFree.restype=ctypes.c_void_p
            ctypes.windll.kernel32.LocalFree(result.data)
    except (KeyError,ValueError,UnicodeError,json.JSONDecodeError):
        raise ValueError('Local '+label+' credential could not be read; reopen the configuration dialog') from None
