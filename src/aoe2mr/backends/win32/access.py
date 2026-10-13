"""Read-only access-right policy.

Every ``OpenProcess`` call goes through :func:`validate_access_mask`. Any right outside the
allowlist (for example write, VM operation, thread creation or "all access") is refused
before Windows is ever called.
"""

from __future__ import annotations

from aoe2mr.backends.win32.constants import (
    PROCESS_QUERY_INFORMATION,
    PROCESS_QUERY_LIMITED_INFORMATION,
    PROCESS_VM_READ,
)
from aoe2mr.errors import ForbiddenAccessRequestError

ALLOWED_ACCESS_MASK = (
    PROCESS_QUERY_LIMITED_INFORMATION | PROCESS_QUERY_INFORMATION | PROCESS_VM_READ
)

# Rights used for basic identification (image path, architecture). Granted for most
# same-user processes, even some that refuse full query rights.
IDENTIFY_ACCESS = PROCESS_QUERY_LIMITED_INFORMATION

# Rights used for region enumeration (VirtualQueryEx documents PROCESS_QUERY_INFORMATION)
# and reading (ReadProcessMemory requires PROCESS_VM_READ).
READ_ACCESS = PROCESS_QUERY_INFORMATION | PROCESS_VM_READ


def validate_access_mask(mask: int) -> int:
    """Return ``mask`` unchanged if it only contains allowlisted read-only rights."""
    if mask <= 0:
        raise ForbiddenAccessRequestError("Access mask must request at least one right")
    forbidden = mask & ~ALLOWED_ACCESS_MASK
    if forbidden:
        raise ForbiddenAccessRequestError(
            f"Access mask 0x{mask:X} contains non-read-only rights 0x{forbidden:X}"
        )
    return mask
