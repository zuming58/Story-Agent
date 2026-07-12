from __future__ import annotations

import ctypes
import os
from ctypes import wintypes
from dataclasses import dataclass
from typing import Protocol


class SecretStoreError(Exception):
    pass


class SecretStoreUnavailable(SecretStoreError):
    pass


class SecretStore(Protocol):
    def set_secret(self, key: str, value: str) -> None:
        ...

    def get_secret(self, key: str) -> str | None:
        ...

    def delete_secret(self, key: str) -> None:
        ...


class MemorySecretStore:
    def __init__(self) -> None:
        self._values: dict[str, str] = {}

    def set_secret(self, key: str, value: str) -> None:
        self._values[key] = value

    def get_secret(self, key: str) -> str | None:
        return self._values.get(key)

    def delete_secret(self, key: str) -> None:
        self._values.pop(key, None)


class UnavailableSecretStore:
    def set_secret(self, key: str, value: str) -> None:
        raise SecretStoreUnavailable("Windows Credential Manager is not available.")

    def get_secret(self, key: str) -> str | None:
        raise SecretStoreUnavailable("Windows Credential Manager is not available.")

    def delete_secret(self, key: str) -> None:
        raise SecretStoreUnavailable("Windows Credential Manager is not available.")


if os.name == "nt":
    ERROR_NOT_FOUND = 1168
    CRED_TYPE_GENERIC = 1
    CRED_PERSIST_LOCAL_MACHINE = 2

    class CREDENTIALW(ctypes.Structure):
        _fields_ = [
            ("Flags", wintypes.DWORD),
            ("Type", wintypes.DWORD),
            ("TargetName", wintypes.LPWSTR),
            ("Comment", wintypes.LPWSTR),
            ("LastWritten", wintypes.FILETIME),
            ("CredentialBlobSize", wintypes.DWORD),
            ("CredentialBlob", ctypes.POINTER(ctypes.c_byte)),
            ("Persist", wintypes.DWORD),
            ("AttributeCount", wintypes.DWORD),
            ("Attributes", wintypes.LPVOID),
            ("TargetAlias", wintypes.LPWSTR),
            ("UserName", wintypes.LPWSTR),
        ]

    advapi32 = ctypes.WinDLL("Advapi32.dll")
    advapi32.CredWriteW.argtypes = [ctypes.POINTER(CREDENTIALW), wintypes.DWORD]
    advapi32.CredWriteW.restype = wintypes.BOOL
    advapi32.CredReadW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.POINTER(ctypes.POINTER(CREDENTIALW))]
    advapi32.CredReadW.restype = wintypes.BOOL
    advapi32.CredDeleteW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD]
    advapi32.CredDeleteW.restype = wintypes.BOOL
    advapi32.CredFree.argtypes = [wintypes.LPVOID]
    advapi32.CredFree.restype = None
    kernel32 = ctypes.WinDLL("Kernel32.dll")
    kernel32.GetLastError.argtypes = []
    kernel32.GetLastError.restype = wintypes.DWORD


@dataclass
class WindowsCredentialStore:
    prefix: str = "StoryAgent"

    def _target(self, key: str) -> str:
        return f"{self.prefix}:{key}"

    def set_secret(self, key: str, value: str) -> None:
        if os.name != "nt":
            raise SecretStoreUnavailable("Windows Credential Manager is not available.")
        blob = value.encode("utf-16-le")
        buffer = ctypes.create_string_buffer(blob)
        credential = CREDENTIALW()  # type: ignore[name-defined]
        credential.Type = CRED_TYPE_GENERIC  # type: ignore[name-defined]
        credential.TargetName = self._target(key)
        credential.CredentialBlobSize = len(blob)
        credential.CredentialBlob = ctypes.cast(buffer, ctypes.POINTER(ctypes.c_byte))
        credential.Persist = CRED_PERSIST_LOCAL_MACHINE  # type: ignore[name-defined]
        credential.UserName = "StoryAgent"
        if not advapi32.CredWriteW(ctypes.byref(credential), 0):  # type: ignore[name-defined]
            raise SecretStoreUnavailable("Failed to write Windows credential.")

    def get_secret(self, key: str) -> str | None:
        if os.name != "nt":
            raise SecretStoreUnavailable("Windows Credential Manager is not available.")
        credential_pointer = ctypes.POINTER(CREDENTIALW)()  # type: ignore[name-defined]
        ok = advapi32.CredReadW(self._target(key), CRED_TYPE_GENERIC, 0, ctypes.byref(credential_pointer))  # type: ignore[name-defined]
        if not ok:
            return None
        try:
            credential = credential_pointer.contents
            raw = ctypes.string_at(credential.CredentialBlob, credential.CredentialBlobSize)
            return raw.decode("utf-16-le")
        finally:
            advapi32.CredFree(credential_pointer)  # type: ignore[name-defined]

    def delete_secret(self, key: str) -> None:
        if os.name != "nt":
            raise SecretStoreUnavailable("Windows Credential Manager is not available.")
        ok = advapi32.CredDeleteW(self._target(key), CRED_TYPE_GENERIC, 0)  # type: ignore[name-defined]
        if not ok:
            error = kernel32.GetLastError()  # type: ignore[name-defined]
            if error != ERROR_NOT_FOUND:  # type: ignore[name-defined]
                raise SecretStoreUnavailable("Failed to delete Windows credential.")


def default_secret_store() -> SecretStore:
    return WindowsCredentialStore() if os.name == "nt" else UnavailableSecretStore()


def secret_preview(value: str) -> str:
    if not value:
        return ""
    return value[-4:] if len(value) <= 8 else value[-6:]
