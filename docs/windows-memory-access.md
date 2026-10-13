# Windows process-memory access: permissions and compatibility

This explains which Windows mechanisms decide whether this tool may observe a process, and
why it must respect each of them.

## APIs used (all documented, user mode)

| Purpose | API | Rights needed |
|---|---|---|
| List processes | `CreateToolhelp32Snapshot`, `Process32FirstW/NextW` | none (no process handle) |
| Executable path | `QueryFullProcessImageNameW` | `PROCESS_QUERY_LIMITED_INFORMATION` |
| Architecture | `IsWow64Process2` (fallback `IsWow64Process`) | `PROCESS_QUERY_LIMITED_INFORMATION` |
| Region list | `VirtualQueryEx` | `PROCESS_QUERY_INFORMATION` (as documented) |
| Read memory | `ReadProcessMemory` | `PROCESS_VM_READ` |
| Privilege info | `IsUserAnAdmin` | none |

The tool opens a process twice at most: once with `QUERY_LIMITED_INFORMATION` to identify it,
and once with `QUERY_INFORMATION | VM_READ` to list regions (and, from M2, read them). The mask
`0x1000 | 0x0400 | 0x0010` is the complete allowlist; anything else is rejected before
`OpenProcess` is called (`backends/win32/access.py`).

## What decides whether access is granted

1. **The process's security descriptor (DACL).** By default a process grants its owner
   (the same user account) full access, so a normal user can read their own normal-level
   processes, including a game they started.
2. **Mandatory integrity control.** Process objects carry a *no-read-up* and *no-write-up*
   policy. A medium-integrity tool (normal user) cannot open a high-integrity (elevated,
   "Run as administrator") process for `VM_READ`. Practical rule: **run the tool and the game
   at the same level, normally both without administrator rights.** The tool does not try
   to elevate itself.
3. **Protected processes (PP/PPL).** System processes, some antimalware services and DRM
   components run protected. Only limited query rights are granted; memory reads are denied
   even to administrators. The tool reports these as `query_only` or `denied`.
4. **Debug privilege.** Administrators can enable a privilege that ignores DACLs. Using it is
   a protection bypass in spirit, so this project never enables it.
5. **Third-party protections.** Some games install anti-cheat drivers that strip handle
   rights. Such protections must be respected, not circumvented (see `feasibility.md`).

When access is refused the tool records `ERROR_ACCESS_DENIED` (5), shows the reason and
moves on. It never retries with broader rights.

## Compatibility considerations

- **64-bit only.** AoE2 DE is a 64-bit process. The tool requires 64-bit Python;
  `MEMORY_BASIC_INFORMATION` uses the 64-bit layout (48 bytes, verified by a unit test).
- **Windows versions.** `IsWow64Process2` exists from Windows 10 1511; older systems fall back
  to `IsWow64Process`. `PROCESS_QUERY_LIMITED_INFORMATION` exists since Vista.
- **ASLR.** Executable, DLL, heap and stack addresses differ on every launch. Persist offsets
  relative to a module base or signatures, never raw addresses.
- **Address space.** User-mode space on x64 is 128 TiB; `VirtualQueryEx` walks it region by
  region (typically thousands to tens of thousands of regions, enumerated in milliseconds).
  Enumeration stops at `ERROR_INVALID_PARAMETER` past the last address and is capped by
  `regions.max_regions`.
- **Region types.** `image` (EXE/DLL sections), `mapped` (file mappings, shared memory) and
  `private` (heaps, stacks, `VirtualAlloc`). Game state almost certainly lives in `private`
  read-write memory.
- **Guard pages and `NOACCESS`.** Reading them fails or has side effects in the target
  (guard pages are one-shot stack probes), so they are reported as not readable and skipped.
- **Partial reads.** `ReadProcessMemory` can return `ERROR_PARTIAL_COPY` (299) when a region
  is freed or re-protected concurrently; the reader raises `MemoryReadError`.
- **Consistency.** Reads are not atomic relative to the game's own threads. The process is
  never suspended (`PROCESS_SUSPEND_RESUME` is not allowlisted).
- **Security software.** Opening other processes with `VM_READ` is legitimate but monitored
  by some products. Minimal rights and no injection keep the tool's behaviour unremarkable.
- **GPU (AMD now, NVIDIA later).** Irrelevant to memory access; matters only for future
  screen-based observation.
