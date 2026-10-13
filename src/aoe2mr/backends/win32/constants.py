"""Win32 constants used by the read-only backend (values from the Windows SDK headers)."""

from __future__ import annotations

# --- Process access rights (winnt.h) ---------------------------------------------------------
# Only these read-only rights are ever requested; see access.py.
PROCESS_VM_READ = 0x0010
PROCESS_QUERY_INFORMATION = 0x0400
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000

# --- Toolhelp ------------------------------------------------------------------------------------
TH32CS_SNAPPROCESS = 0x00000002
INVALID_HANDLE_VALUE = -1

# --- Memory states (MEMORY_BASIC_INFORMATION.State) -------------------------------------------
MEM_COMMIT = 0x00001000
MEM_RESERVE = 0x00002000
MEM_FREE = 0x00010000

# --- Memory types (MEMORY_BASIC_INFORMATION.Type) ---------------------------------------------
MEM_PRIVATE = 0x00020000
MEM_MAPPED = 0x00040000
MEM_IMAGE = 0x01000000

# --- Page protection (base values are mutually exclusive, modifiers are OR-ed) ---------------
PAGE_NOACCESS = 0x01
PAGE_READONLY = 0x02
PAGE_READWRITE = 0x04
PAGE_WRITECOPY = 0x08
PAGE_EXECUTE = 0x10
PAGE_EXECUTE_READ = 0x20
PAGE_EXECUTE_READWRITE = 0x40
PAGE_EXECUTE_WRITECOPY = 0x80
PAGE_GUARD = 0x100
PAGE_NOCACHE = 0x200
PAGE_WRITECOMBINE = 0x400

PAGE_BASE_MASK = 0xFF
PAGE_MODIFIER_MASK = PAGE_GUARD | PAGE_NOCACHE | PAGE_WRITECOMBINE

# --- Machine types (IsWow64Process2) ------------------------------------------------------------
IMAGE_FILE_MACHINE_UNKNOWN = 0x0000
IMAGE_FILE_MACHINE_I386 = 0x014C
IMAGE_FILE_MACHINE_ARMNT = 0x01C4
IMAGE_FILE_MACHINE_AMD64 = 0x8664
IMAGE_FILE_MACHINE_ARM64 = 0xAA64

# --- Win32 error codes (winerror.h) -------------------------------------------------------------
ERROR_ACCESS_DENIED = 5
ERROR_INVALID_PARAMETER = 87
ERROR_PARTIAL_COPY = 299
ERROR_NO_MORE_FILES = 18
