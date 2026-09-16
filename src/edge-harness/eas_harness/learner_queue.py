"""Windows learner IPC: ACL-scoped JSON files, with no execution credential.

The learner runs as its own noninteractive user. Its response is untrusted and
is checked by the protected admission runtime against the original evidence.
"""

import json
import os
from pathlib import Path
import time
import uuid


def read_response(path):
    """Do not follow a learner-created link with executor file privileges."""
    if os.name == "nt":
        import ctypes
        from ctypes import wintypes
        import msvcrt

        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.CreateFileW.argtypes = [
            wintypes.LPCWSTR,
            wintypes.DWORD,
            wintypes.DWORD,
            ctypes.c_void_p,
            wintypes.DWORD,
            wintypes.DWORD,
            wintypes.HANDLE,
        ]
        kernel.CreateFileW.restype = wintypes.HANDLE
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel.GetFileInformationByHandleEx.argtypes = [
            wintypes.HANDLE,
            ctypes.c_int,
            ctypes.c_void_p,
            wintypes.DWORD,
        ]
        handle = kernel.CreateFileW(str(path), 0x80000000, 7, None, 3, 0x00200000, None)
        if handle == wintypes.HANDLE(-1).value:
            raise OSError(ctypes.get_last_error(), "Cannot open learner response")
        attributes = (wintypes.DWORD * 2)()
        if (
            not kernel.GetFileInformationByHandleEx(
                handle, 9, ctypes.byref(attributes), ctypes.sizeof(attributes)
            )
            or attributes[0] & 0x400
        ):
            kernel.CloseHandle(handle)
            raise ValueError("Learner response must be a regular file")
        fd = msvcrt.open_osfhandle(handle, os.O_RDONLY | os.O_BINARY)
    else:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(fd, "rb") as file:
        raw = file.read(80001)
    if len(raw) > 80000:
        raise ValueError("Learner output exceeds budget")
    return json.loads(raw)


def propose(root, payload):
    root = Path(root)
    identity = uuid.uuid4().hex
    pending, request = (root / "requests" / (identity + suffix) for suffix in (".pending", ".request"))
    response = root / "responses" / (identity + ".response")
    try:
        pending.write_text(json.dumps(payload), encoding="utf-8")
        pending.replace(request)
        deadline = time.monotonic() + 45
        while time.monotonic() < deadline:
            if response.exists():
                result = read_response(response)
                if "error" in result:
                    raise ValueError("Isolated learner failed; no candidate admitted")
                return result
            time.sleep(0.1)
        raise ValueError("Isolated learner timed out; no candidate admitted")
    finally:
        for file in (pending, request, response):
            try:
                file.unlink(missing_ok=True)
            except OSError:
                pass


def serve():
    from eas_harness.maintenance import subprocess_json

    root = Path(os.environ["EAS_LEARNER_QUEUE"])
    # Avoid recursively routing this account's model process back to the queue.
    os.environ.pop("EAS_LEARNER_QUEUE")
    while True:
        for path in (root / "requests").glob("*.request"):
            response = root / "responses" / (path.stem + ".response")
            if response.exists():
                continue
            try:
                if path.is_symlink() or path.stat().st_size > 600000:
                    raise ValueError("Invalid learner request")
                payload = json.loads(path.read_text(encoding="utf-8"))
                result = subprocess_json(
                    "eas_harness.learner_process", payload, model_key=payload["model_mode"] == "live"
                )
            except Exception:
                result = {"error": "Learner request failed"}
            if path.exists():
                temporary = response.with_suffix(".pending")
                temporary.write_text(json.dumps(result), encoding="utf-8")
                temporary.replace(response)
        time.sleep(0.25)
