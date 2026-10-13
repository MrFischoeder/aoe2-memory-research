"""Static guard rails: the source tree must not reference APIs that modify other processes,
inject code, synthesize input or bypass protections. See docs/safety-policy.md."""

from __future__ import annotations

import re
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src" / "aoe2mr"

FORBIDDEN_IDENTIFIERS = [
    # memory modification / injection
    "WriteProcessMemory", "NtWriteVirtualMemory", "ZwWriteVirtualMemory",
    "VirtualAllocEx", "VirtualProtectEx", "VirtualFreeEx",
    "CreateRemoteThread", "NtCreateThreadEx", "RtlCreateUserThread", "QueueUserAPC",
    "SetThreadContext", "LoadLibrary", "SetWindowsHookEx",
    "PROCESS_VM_WRITE", "PROCESS_VM_OPERATION", "PROCESS_CREATE_THREAD", "PROCESS_ALL_ACCESS",
    "DebugActiveProcess",
    # privilege escalation / protection bypass
    "SeDebugPrivilege", "AdjustTokenPrivileges", "NtLoadDriver", "CreateService",
    # input automation
    "SendInput", "keybd_event", "mouse_event", "PostMessage", "SendMessage",
    "pyautogui", "pynput",
]


def _source_files() -> list[Path]:
    files = sorted(SRC.rglob("*.py"))
    assert files, "source tree not found"
    return files


def test_no_forbidden_identifiers_in_source() -> None:
    offenders = []
    for path in _source_files():
        text = path.read_text(encoding="utf-8")
        for ident in FORBIDDEN_IDENTIFIERS:
            if re.search(rf"\b{re.escape(ident)}\b", text):
                offenders.append(f"{path.relative_to(SRC)}: {ident}")
    assert offenders == []


def test_open_process_only_called_through_policy() -> None:
    callers = [p.relative_to(SRC).as_posix() for p in _source_files()
               if "OpenProcess(" in p.read_text(encoding="utf-8")]
    assert callers == ["backends/win32/api.py"]
    api_text = (SRC / "backends" / "win32" / "api.py").read_text(encoding="utf-8")
    init = api_text[api_text.index("class ProcessHandle"):]
    assert init.index("validate_access_mask(access)") < init.index("k.OpenProcess(")
