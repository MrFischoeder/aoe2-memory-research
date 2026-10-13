# Safety policy

## Hard limits (this phase)

1. Read-only process access only.
2. No writes to any other process's memory.
3. No code, DLL or thread injection; no hooks.
4. No kernel drivers; no disabling of security features; no debug privileges.
5. No anti-cheat bypass. If the game refuses access, that is the final answer.
6. Single-player only; no multiplayer integration.
7. No hidden-information exploitation (fog of war, opponent state).
8. No automated mouse or keyboard input.
9. No persistent background monitoring without explicit user activation.

## How the code enforces it

| Mechanism | Where |
|---|---|
| Access-right allowlist (`QUERY_LIMITED_INFORMATION`, `QUERY_INFORMATION`, `VM_READ`), checked before every `OpenProcess` | `src/aoe2mr/backends/win32/access.py`, `api.py` |
| Unit tests proving write/control rights (VM_WRITE, VM_OPERATION, CREATE_THREAD, ALL_ACCESS, ...) are rejected | `tests/test_win32_layer.py` |
| Static test failing the build if the source tree mentions process-modifying, injection, privilege or input-synthesis APIs | `tests/test_safety_policy.py` |
| Static test ensuring `OpenProcess` is called in exactly one place, after validation | `tests/test_safety_policy.py` |
| Denials are reported, never retried with other rights | `process_discovery/discovery.py` |
| All commands are one-shot and user-initiated | `cli.py` |

Changes that weaken any of these require an explicit decision by the project owner and an
update of this document.
